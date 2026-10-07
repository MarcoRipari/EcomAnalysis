"""
EcomAnalysis — API dati esterna v1 (FastAPI + Uvicorn).

Espone in LETTURA i dati del DB SQLite condiviso (data/ecombi.db) verso strumenti
esterni: Excel/Power Query, Power BI, script, applicazioni di terze parti.

- ZERO logica di business qui: le letture passano da core/db.py (query_period,
  get_data_bounds, get_stats, get_upload_log) e core/metrics.py
  (compute_channel_kpi) — le stesse funzioni usate dalle pagine Streamlit,
  quindi le cifre coincidono SEMPRE con l'app.
- Autenticazione (una delle due, in alternativa):
    1) header X-API-Key: chiave generata dalla pagina "Account e 2FA"
       dell'app (consigliata per Excel/Power BI/script);
    2) header Authorization: Bearer <access token Supabase> (per
       integrazioni con login programmatico).
- Lancio dalla root del repo:
      venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8001
- Documentazione interattiva: http://127.0.0.1:8001/api/docs

Variabili d'ambiente (api/.env — SOLO sul VPS, mai committato):
  SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY,
  ECOM_DB_PATH (default data/ecombi.db),
  ECOM_API_MAX_RIGHE (default 50000), ECOM_API_CACHE_TTL secondi (default 300)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response

# la root del repo (dove vivono core/ e data/) deve essere importabile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import db as ecd
from core import metrics as ecm


# ---------------------------------------------------------------------------------------
# Configurazione (api/.env)
# ---------------------------------------------------------------------------------------
def _load_env() -> None:
    p = Path(__file__).resolve().parent / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or ""
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
DB_PATH = os.environ.get("ECOM_DB_PATH") or str(
    Path(__file__).resolve().parents[1] / "data" / "ecombi.db")
MAX_RIGHE = int(os.environ.get("ECOM_API_MAX_RIGHE") or 50_000)
CACHE_TTL = int(os.environ.get("ECOM_API_CACHE_TTL") or 300)  # cache validazione chiavi

_GRUPPI = {"mkp": "mkp", "nazione": "nazione", "brand": "clzMappata",
           "genere": "genere", "taglia": "taglia", "sku": "sku13",
           "acquirente": "acquirente"}
_SUM = ("paiaSpedite", "paiaRese", "paiaNette", "nettoSpedito", "nettoReso",
        "nettoNetto", "lordoSpedito", "lordoReso", "lordoNetto")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    mancanti = [n for n, v in (("SUPABASE_URL", SUPABASE_URL),
                               ("SUPABASE_ANON_KEY", SUPABASE_ANON_KEY),
                               ("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_SERVICE_ROLE_KEY)) if not v]
    if mancanti:
        raise RuntimeError(f"api/.env incompleto — mancanti: {', '.join(mancanti)}")
    yield


app = FastAPI(
    title="EcomAnalysis API",
    version="1.0.0",
    description="Dati vendite/resi in lettura per Excel, Power BI, script e integrazioni.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------------------
# Autenticazione: chiave API (hash su Supabase) oppure Bearer JWT
# ---------------------------------------------------------------------------------------
_KEY_CACHE: dict[str, tuple[dict, float]] = {}   # hash → (riga, scadenza cache)
_LAST_USED: dict[str, float] = {}                # hash → ts ultima PATCH last_used_at


def _service_headers() -> dict:
    return {"apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json"}


def verify_api_key(key: str) -> dict:
    key = key.strip()
    if not key.startswith("ecm_") or len(key) < 12:
        raise HTTPException(401, "Formato chiave API non valido (deve iniziare con 'ecm_').")
    h = hashlib.sha256(key.encode()).hexdigest()

    riga = None
    hit = _KEY_CACHE.get(h)
    if hit and hit[1] > time.time():
        riga = hit[0]
    else:
        url = (f"{SUPABASE_URL}/rest/v1/api_keys"
               f"?select=id,name,prefix,user_id,created_at,revoked_at,last_used_at"
               f"&key_hash=eq.{h}")
        try:
            r = requests.get(url, headers=_service_headers(), timeout=10)
        except requests.RequestException:
            raise HTTPException(503, "Supabase non raggiungibile: riprova più tardi.")
        if r.status_code != 200:
            raise HTTPException(502, f"Errore Supabase ({r.status_code}) in validazione chiave.")
        trovate = r.json()
        if not trovate:
            raise HTTPException(401, "Chiave API non valida o eliminata.")
        riga = trovate[0]
        _KEY_CACHE[h] = (riga, time.time() + CACHE_TTL)

    if riga.get("revoked_at"):
        raise HTTPException(403, "Chiave API revocata: generane una nuova dalla pagina Account.")

    # aggiorna last_used_at al massimo ogni CACHE_TTL secondi (best-effort)
    if _LAST_USED.get(h, 0) < time.time() - CACHE_TTL:
        try:
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/api_keys?id=eq.{riga['id']}",
                headers=_service_headers(),
                json={"last_used_at": datetime.now(timezone.utc).isoformat()},
                timeout=5)
            _LAST_USED[h] = time.time()
        except requests.RequestException:
            pass

    return {"via": "api_key", "nome": riga.get("name"), "chiave_id": riga.get("id"),
            "user_id": riga.get("user_id"), "prefisso": riga.get("prefix")}


def verify_jwt(token: str) -> dict:
    try:
        r = requests.get(f"{SUPABASE_URL}/auth/v1/user",
                         headers={"apikey": SUPABASE_ANON_KEY,
                                  "Authorization": f"Bearer {token}"}, timeout=10)
    except requests.RequestException:
        raise HTTPException(503, "Supabase non raggiungibile: riprova più tardi.")
    if r.status_code in (401, 403):
        raise HTTPException(401, "Token non valido o scaduto.")
    if r.status_code != 200:
        raise HTTPException(502, f"Errore Supabase ({r.status_code}) in validazione token.")
    u = r.json()
    return {"via": "jwt", "nome": u.get("email"), "user_id": u.get("id"), "prefisso": None}


def require_auth(x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                 authorization: str | None = Header(default=None)) -> dict:
    """Dipendenza FastAPI: serve una delle due credenziali, altrimenti 401."""
    if x_api_key:
        return verify_api_key(x_api_key)
    if authorization and authorization.lower().startswith("bearer "):
        return verify_jwt(authorization[7:].strip())
    raise HTTPException(401, "Autenticazione richiesta: header 'X-API-Key' (chiave API) "
                             "oppure 'Authorization: Bearer <token>'.")


# ---------------------------------------------------------------------------------------
# Helper dati / formati
# ---------------------------------------------------------------------------------------
def _filtra(df: pd.DataFrame, **colonne: str | None) -> pd.DataFrame:
    """Filtro di uguaglianza case-insensitive, multi-valore separato da virgola.
    Uso: _filtra(df, mkp="ZALANDO", nazione="IT,DE", clzMappata="NATURINO")."""
    for col, val in colonne.items():
        if not val or col not in df.columns:
            continue
        voluti = {s.strip().upper() for s in val.split(",") if s.strip()}
        if voluti:
            df = df[df[col].astype(str).str.upper().isin(voluti)]
    return df


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → lista di dict JSON-safe (NaN/NaT→null, Timestamp→YYYY-MM-DD)."""
    if df.empty:
        return []
    out: list[dict] = []
    for riga in df.to_dict("records"):
        r: dict[str, Any] = {}
        for k, v in riga.items():
            if v is None or v is pd.NaT or (isinstance(v, float) and pd.isna(v)):
                r[k] = None
            elif isinstance(v, pd.Timestamp):
                r[k] = v.date().isoformat()
            elif isinstance(v, np.integer):
                r[k] = int(v)
            elif isinstance(v, np.floating):
                r[k] = float(v)
            elif isinstance(v, np.bool_):
                r[k] = bool(v)
            else:
                r[k] = v
        out.append(r)
    return out


def _date_leggibili(df: pd.DataFrame) -> pd.DataFrame:
    """Per csv/md/txt: le colonne data diventano stringhe YYYY-MM-DD (vuoto se nulle)."""
    df = df.copy()
    for c in ("dataVendita", "dataReso"):
        if c in df.columns and len(df):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    return df


def _df_md(df: pd.DataFrame) -> str:
    def cell(v):
        if v is None or v is pd.NaT or (isinstance(v, float) and pd.isna(v)):
            return "—"
        if isinstance(v, (float, np.floating)):
            return f"{float(v):,.2f}"
        if isinstance(v, (int, np.integer)):
            return f"{int(v):,}"
        return str(v).replace("|", "/")
    cols = list(df.columns)
    righe = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in df.itertuples(index=False):
        righe.append("| " + " | ".join(cell(v) for v in r) + " |")
    return "\n".join(righe)


# ---------------------------------------------------------------------------------------
# Presentazione output — nomi colonna pubblici + formati valori (solo csv/md/txt)
# ---------------------------------------------------------------------------------------
# Rinomina dei nomi "grezzi" delle colonne del DB nei nomi pubblici usati dall'app
# (stessa mappa di nazioni_brand_share in core/report_builders.py: clzMappata→Brand,
# nettoNetto→Fatturato Netto, paiaSpedite→Paia spedite, …). Vale per TUTTI gli endpoint
# e TUTTI i formati di output, JSON compreso: nel JSON i VALORI restano numerici
# (per Excel/Power BI/script), cambiano solo i nomi delle colonne.
_RENAME_COLONNE = {
    "mkp": "Marketplace", "nazione": "Nazione",
    "clzMappata": "Brand", "clzOriginale": "Collezione",
    "genere": "Genere", "taglia": "Taglia", "sku13": "SKU", "sku7": "Codice",
    "acquirente": "Acquirente", "ordineId": "Ordine", "rigaId": "Riga ordine",
    "dataVendita": "Data vendita", "dataReso": "Data reso",
    "isReso": "Reso", "stato": "Stato", "tipoSpedizione": "Tipo spedizione",
    "paiaSpedite": "Paia spedite", "paiaRese": "Paia rese", "paiaNette": "Paia nette",
    "nettoSpedito": "Netto spedito", "nettoReso": "Netto reso", "nettoNetto": "Fatturato netto",
    "lordoSpedito": "Lordo spedito", "lordoReso": "Lordo reso", "lordoNetto": "Lordo netto",
    "ordini": "Ordini", "righe": "Righe",
}


def _it_num(x: float, decimali: int = 2) -> str:
    """Numero in stile italiano: 1.234,56 (punto migliaia, virgola decimali)."""
    s = f"{x:,.{decimali}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_valuta(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return f"{_it_num(float(x), 2)} €"


def _fmt_intero(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return _it_num(round(float(x)), 0)


def _fmt_perc(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return f"{_it_num(float(x) * 100, 1)}%"


def _fmt_var(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    segno = "+" if x >= 0 else "-"
    return f"{segno}{_it_num(abs(float(x)) * 100, 1)}%"


def _tipo_colonna(nome: str) -> str | None:
    """Classifica una colonna per la presentazione, coprendo TUTTE le colonne di TUTTI
    gli endpoint e report: 'valuta' | 'intero' | 'percent' | 'var' (variazione % con
    segno). None = lasciare il valore com'è (testi, date, contatori generici).

    Esempi: 'Fatturato Netto', 'Fatt.Netto 2026', 'Netto spedito', 'Scontrino Medio',
    'Margine Lordo' → valuta · 'Ordini', 'Paia spedite', 'Righe' → intero ·
    '% Reso', 'Share %', 'Reso % (valore)' → percent · 'VAR% FATT', 'Var % Ordini YoY'
    → var."""
    n = str(nome).strip().lower()
    if "%" in n:
        return "var" if n.startswith("var") else "percent"
    if "ordini" in n or "righe" in n or "paia" in n:
        return "intero"
    if ("fatt" in n or "netto" in n or "lordo" in n or "scontrino" in n
            or "margine" in n or "valore medio" in n):
        return "valuta"
    return None


def _pretty_df(df: pd.DataFrame) -> pd.DataFrame:
    """Per csv/md/txt: nomi colonna pubblici + valori formattati in stile italiano —
    valute '1.234,56 €' (€ alla fine), interi senza decimali ('0' e non '0.00'),
    percentuali '50,0%' (e non 0.50), variazioni '+12,3%' con segno.
    Si applica solo alle colonne NUMERICHE: le tabelle già formattate come stringa
    (es. kpi_block, che è stringa di proposito per i tipi misti per riga) restano
    invariate. Il JSON non passa di qui: resta numerico."""
    out = df.rename(columns=_RENAME_COLONNE).copy()
    for c in out.columns:
        t = _tipo_colonna(c)
        if t is None or not pd.api.types.is_numeric_dtype(out[c]):
            continue
        if t == "valuta":
            out[c] = out[c].map(_fmt_valuta)
        elif t == "intero":
            out[c] = out[c].map(_fmt_intero)
        elif t == "var":
            out[c] = out[c].map(_fmt_var)
        else:
            out[c] = out[c].map(_fmt_perc)
    return out


def _limita(df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    if len(df) > MAX_RIGHE:
        return (df.head(MAX_RIGHE).reset_index(drop=True),
                f"Risultato troncato: prime {MAX_RIGHE} righe su {len(df)}. "
                "Restringi il periodo, usa filtri o level=group.")
    if df.empty:
        return df, "Nessuna riga trovata per i parametri richiesti."
    return df, None


def _rispondi(df: pd.DataFrame, fmt: str, parametri: dict, nome: str,
              avviso: str | None = None, download: bool = False) -> Response:
    if avviso:
        parametri = {**parametri, "avviso": avviso}
    if fmt == "json":
        return JSONResponse({"ok": True, "parametri": parametri,
                             "righe": int(len(df)),
                             "dati": _records(df.rename(columns=_RENAME_COLONNE))})
    df = _pretty_df(_date_leggibili(df))
    if fmt == "csv":
        corpo, media = df.to_csv(index=False, lineterminator="\n"), "text/csv; charset=utf-8"
    elif fmt == "md":
        corpo = ("**" + nome + "** — parametri: "
                 + ", ".join(f"{k}={v}" for k, v in parametri.items())
                 + "\n\n" + _df_md(df) + "\n")
        media = "text/markdown; charset=utf-8"
    else:  # txt
        corpo, media = df.to_string(index=False, max_colwidth=28), "text/plain; charset=utf-8"
    headers = {"X-Ecom-Parametri": json.dumps(parametri, ensure_ascii=False)}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{nome}.{fmt}"'
    return Response(corpo, media_type=media, headers=headers)


def _filtri_comuni(mkp, nazione, brand, sku, genere, taglia, acquirente) -> dict:
    return {k: v for k, v in (("mkp", mkp), ("nazione", nazione), ("brand", brand),
                              ("sku", sku), ("genere", genere), ("taglia", taglia),
                              ("acquirente", acquirente)) if v}


def _apri_e_query(da: date, a: date, perimetro: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    conn = ecd.connect(DB_PATH)
    venduto, standalone = ecd.query_period(conn, da, a, perimetro)
    conn.close()
    return venduto, standalone


def _kpi_payload(venduto: pd.DataFrame, standalone: pd.DataFrame, parametri: dict) -> JSONResponse:
    k = ecm.compute_channel_kpi(venduto, standalone)
    return JSONResponse({"ok": True, "parametri": parametri, "kpi": {
        "fatturatoNettoReale": round(float(k["fattReale"]), 2),
        "ordini": int(k["ordini"]),
        "paiaNette": float(k["paiaNette"]),
        "valoreMedioPaio": round(float(k["valMedio"]), 2),
        "tassoResoPaia": round(float(k["percReso"]), 4),
        "fatturatoNettoSpedito": round(float(venduto["nettoSpedito"].sum()), 2),
        "fatturatoLordoSpedito": round(float(venduto["lordoSpedito"].sum()), 2),
        "paiaSpedite": float(venduto["paiaSpedite"].sum()),
        "paiaReseInPeriodo": float(venduto["paiaRese"].sum()),
        "righeVendite": int(len(venduto)),
        "righeRimborsiExtra": int(len(standalone)),
    }})


# ---------------------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------------------
@app.get("/api/v1/health")
def health() -> dict:
    """Stato del servizio + statistiche del DB (nessuna autenticazione)."""
    try:
        conn = ecd.connect(DB_PATH)
        stats = ecd.get_stats(conn)
        conn.close()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "servizio": "EcomAnalysis API v1", "db": f"errore: {e}"}
    return {"ok": True, "servizio": "EcomAnalysis API v1", "db": stats}


@app.get("/api/v1/me")
def me(ident: dict = Depends(require_auth)) -> dict:
    """Chi sta chiamando: tipo di credenziale e nome associato."""
    return {"ok": True, "via": ident["via"], "nome": ident["nome"]}


@app.get("/api/v1/periodi")
def periodi(ident: dict = Depends(require_auth)) -> dict:
    """Copertura dei dati nel DB, conteggi e ultimi caricamenti."""
    conn = ecd.connect(DB_PATH)
    stats = ecd.get_stats(conn)
    log = ecd.get_upload_log(conn, limit=20)
    conn.close()
    return {"ok": True,
            "copertura": {"da": stats["data_min"], "a": stats["data_max"]},
            "righe": {k: stats[k] for k in ("righe_totali", "spediti", "resi", "standalone")},
            "ultimiCaricamenti": _records(log)}


def _check_periodo(da: date, a: date) -> None:
    if da > a:
        raise HTTPException(400, f"Periodo invertito: 'da' ({da}) è successivo ad 'a' ({a}).")


@app.get("/api/v1/vendite")
def vendite(
    da: date, a: date,
    perimetro: str = Query("1", pattern="^[123]$",
                           description="1 totale, 2 solo diretti, 3 solo logistica esterna"),
    level: str = Query("raw", pattern="^(raw|group|kpi)$"),
    group: str | None = Query(None, pattern="^(mkp|nazione|brand|genere|taglia|sku|acquirente)$"),
    fmt: str = Query("json", alias="format", pattern="^(json|csv|md|txt)$"),
    mkp: str | None = None, nazione: str | None = None, brand: str | None = None,
    sku: str | None = None, genere: str | None = None, taglia: str | None = None,
    acquirente: str | None = None,
    download: bool = False,
    ident: dict = Depends(require_auth),
) -> Response:
    """Righe di vendita del periodo (data vendita tra `da` e `a`, estremi inclusi).

    level=raw   → le singole righe (json/csv/md/txt)
    level=group → righe aggregate per `group` (default mkp), ordinate per netto decrescente
    level=kpi  → sintesi del periodo (solo json; ignora format/group)
    """
    _check_periodo(da, a)
    filtri = _filtri_comuni(mkp, nazione, brand, sku, genere, taglia, acquirente)

    if level == "kpi":
        if fmt != "json":
            raise HTTPException(400, "level=kpi supporta solo format=json.")
        venduto, standalone = _apri_e_query(da, a, perimetro)
        parametri = {"da": str(da), "a": str(a), "perimetro": perimetro,
                     "level": "kpi", "filtri": filtri}
        return _kpi_payload(_filtra(venduto, **_mappa_filtri(filtri)),
                             _filtra(standalone, **_mappa_filtri(filtri)), parametri)

    venduto, _ = _apri_e_query(da, a, perimetro)
    venduto = _filtra(venduto, **_mappa_filtri(filtri))
    parametri = {"da": str(da), "a": str(a), "perimetro": perimetro, "level": level,
                 "group": group, "filtri": filtri}

    if level == "group":
        col = _GRUPPI[group or "mkp"]
        g = venduto.groupby(col, dropna=False, observed=True)
        df = g[list(_SUM)].sum().reset_index()
        df["ordini"] = g["ordineId"].nunique().to_numpy()
        df["righe"] = g.size().to_numpy()
        df = df.sort_values("nettoNetto", ascending=False,
                            na_position="last").reset_index(drop=True)
    else:
        df = venduto

    df, avviso = _limita(df)
    return _rispondi(df, fmt, parametri, f"vendite_{da}_{a}", avviso, download)


def _mappa_filtri(filtri: dict) -> dict:
    """Parametri pubblici → colonne del DataFrame restituito da query_period."""
    return {"mkp": filtri.get("mkp"), "nazione": filtri.get("nazione"),
            "clzMappata": filtri.get("brand"), "sku13": filtri.get("sku"),
            "genere": filtri.get("genere"), "taglia": filtri.get("taglia"),
            "acquirente": filtri.get("acquirente")}


@app.get("/api/v1/resi")
def resi(
    da: date, a: date,
    perimetro: str = Query("1", pattern="^[123]$"),
    tipo: str = Query("in_periodo", pattern="^(in_periodo|extra)$"),
    fmt: str = Query("json", alias="format", pattern="^(json|csv|md|txt)$"),
    mkp: str | None = None, nazione: str | None = None, brand: str | None = None,
    sku: str | None = None, genere: str | None = None, taglia: str | None = None,
    acquirente: str | None = None,
    download: bool = False,
    ident: dict = Depends(require_auth),
) -> Response:
    """Resi del periodo (data reso tra `da` e `a`).

    tipo=in_periodo → resi di vendite SPEDITE nel periodo e rientrate nel periodo
    tipo=extra       → rimborsi "standalone": resi nel periodo la cui vendita non è
                       nel periodo/esistente (stessa semantica dell'app: decrementano
                       il fatturato reale del periodo)
    """
    _check_periodo(da, a)
    filtri = _filtri_comuni(mkp, nazione, brand, sku, genere, taglia, acquirente)
    venduto, standalone = _apri_e_query(da, a, perimetro)
    if tipo == "extra":
        df = standalone
    else:
        df = venduto[venduto["isReso"].astype(bool)].reset_index(drop=True)
    df = _filtra(df, **_mappa_filtri(filtri))
    parametri = {"da": str(da), "a": str(a), "perimetro": perimetro,
                 "tipo": tipo, "filtri": filtri}
    df, avviso = _limita(df)
    return _rispondi(df, fmt, parametri, f"resi_{tipo}_{da}_{a}", avviso, download)


@app.get("/api/v1/kpi")
def kpi(
    da: date, a: date,
    perimetro: str = Query("1", pattern="^[123]$"),
    mkp: str | None = None, nazione: str | None = None, brand: str | None = None,
    sku: str | None = None, genere: str | None = None, taglia: str | None = None,
    acquirente: str | None = None,
    ident: dict = Depends(require_auth),
) -> JSONResponse:
    """Sintesi del periodo: i KPI principali, con lo stesso calcolo dell'app.

    fatturatoNettoReale = netto spedito − resi in periodo − rimborsi extra
    (identico a compute_channel_kpi usato dalle pagine di report).
    """
    _check_periodo(da, a)
    filtri = _filtri_comuni(mkp, nazione, brand, sku, genere, taglia, acquirente)
    venduto, standalone = _apri_e_query(da, a, perimetro)
    parametri = {"da": str(da), "a": str(a), "perimetro": perimetro, "filtri": filtri}
    return _kpi_payload(_filtra(venduto, **_mappa_filtri(filtri)),
                        _filtra(standalone, **_mappa_filtri(filtri)), parametri)


# ---------------------------------------------------------------------------------------
# Report — estrae i report delle pagine dell'app riusando core/report_builders.py
# (le stesse identiche funzioni/tabelle/cifre che l'app renderizza in Streamlit).
# ---------------------------------------------------------------------------------------
from core import aggregations as aggm
from core import engine as eceng
from core import pipeline as ecp
from core import report_builders as rbm

_TIPI_REPORT = ("dashboard", "y2y_generale", "y2y_collezioni", "y2y_codici",
                "taglie", "resi", "nazioni", "unificato", "mensile")
_DIM_REPORT = {"mkp": "mkp", "nazione": "nazione", "brand": "clzMappata"}


def _shift_year(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:                     # 29 febbraio → 28
        return d.replace(year=d.year + n, day=28)


def _anagrafica() -> dict:
    """L'anagrafica articoli usata dall'app per le descrizioni (se raggiungibile)."""
    try:
        return eceng.load_anagrafica() or {}
    except Exception:
        return {}


def _build_pipe(da: date, a: date, confronto: tuple | None, perimetro: str):
    conn = ecd.connect(DB_PATH)
    try:
        return ecp.build_pipeline_from_db(conn, (da, a), confronto, perimetro, _anagrafica())
    finally:
        conn.close()


def _filtra_report(pipe, filtri: dict) -> None:
    """Applica i filtri a TUTTE le fonti dati del report (corrente, confronto, rimborsi)."""
    m = _mappa_filtri(filtri)
    pipe.current_data = _filtra(pipe.current_data, **m)
    pipe.old_data = _filtra(pipe.old_data, **m)
    pipe.esito_resi_current["standalone"] = _filtra(pipe.esito_resi_current["standalone"], **m)
    pipe.esito_resi_old["standalone"] = _filtra(pipe.esito_resi_old["standalone"], **m)


def _skip_clz(key_name, row):
    """Stesso skip della pagina Y2Y Collezioni: livelli 'clzOriginale' vuoti/ALTRO
    uguali al brand mappato non vengono duplicati nell'alberatura."""
    if key_name == "clzOriginale":
        orig = str(row.get("clzOriginale") or "").strip().upper()
        mapv = str(row.get("clzMappata") or "").strip().upper()
        return (not orig) or orig == "ALTRO" or orig == mapv
    return False


def _sezioni_report(tipo: str, pipe, y_curr: str, dim: str, top: int,
                    nazioni: list[str] | None,
                    periodi_confronto: list[tuple[str, pd.DataFrame, pd.DataFrame]],
                    da: date, a: date
                    ) -> list[tuple[str, pd.DataFrame]]:
    """Lista [(titolo, DataFrame)]: replica le chiamate alle stesse funzioni delle pagine.

    Regola periodi (a richiesta): `confronti` = 0/1/2 lo decide l'endpoint —
    0 = solo periodo scelto; 1 = + anno-1; 2 = + anno-1 e anno-2.
    `periodi_confronto` = [(etichetta-anno, df vendite, df rimborsi extra)] dei
    periodi richiesti e effettivamente coperti dal DB (già filtrati);
    con confronti=0 è una lista vuota e i report mostrano solo l'anno scelto.
    """
    cur = pipe.current_data
    sc = pipe.esito_resi_current["standalone"]
    out: list[tuple[str, pd.DataFrame]] = []

    if tipo == "dashboard":
        def _dash(df: pd.DataFrame, y: str) -> list[tuple[str, pd.DataFrame]]:
            return [
                ("Dettaglio Marketplace",
                 rbm.single_year_table(aggm.aggregate_by_key(df, "mkp"), y, "fatturatoNetto")),
                ("Dettaglio Nazioni",
                 rbm.single_year_table(aggm.aggregate_by_key(df, "nazione"), y, "fatturatoNetto")),
                ("Dettaglio Collezioni",
                 rbm.single_year_table(aggm.aggregate_by_key(df, "clzMappata"), y, "paiaNette")),
                ("Top Articoli", rbm.top_articoli_dashboard(df, pipe.anagrafica, top_n=top)),
            ]
        out += [(f"{t} — {y_curr}", d) for t, d in _dash(cur, y_curr)]
        for y, old, _ in periodi_confronto:
            out += [(f"{t} — {y}", d) for t, d in _dash(old, y)]
        return out

    if tipo == "y2y_generale":
        for y, old, so in periodi_confronto:
            kpi = rbm.kpi_block(ecm.compute_channel_kpi(cur, sc),
                                ecm.compute_channel_kpi(old, so), y_curr, y)
            if kpi is not None:
                out.append((f"KPI Principali — {y_curr} vs {y}", kpi))
            out.append((f"Andamento Mensile — {y_curr} vs {y}",
                        rbm.monthly_trend(cur, old, sc, so, y_curr, y)))
        col = _DIM_REPORT[dim]
        for y, old, _ in periodi_confronto:
            out.append((f"Comparativa per {dim} — {y_curr} vs {y}",
                        rbm.comparative_table(aggm.aggregate_by_key(cur, col),
                                              aggm.aggregate_by_key(old, col), y_curr, y, "fatturatoNetto")))
            out.append((f"Top Articoli — {y_curr} vs {y}",
                        rbm.top_articoli_y2y(cur, old, pipe.anagrafica, y_curr, y, top_n=top)))

    elif tipo == "y2y_collezioni":
        alberature = [
            ("Analisi Brand / Collezione",
             ["clzMappata", "clzOriginale"], ["Brand", "Collezione Originale"], None),
            ("Dettaglio per Marketplace",
             ["clzMappata", "mkp", "nazione", "clzOriginale"],
             ["Brand", "Marketplace", "Nazione", "Collezione"], _skip_clz),
            ("Dettaglio per Nazione",
             ["clzMappata", "nazione", "mkp", "clzOriginale"],
             ["Brand", "Nazione", "Marketplace", "Collezione"], _skip_clz),
        ]
        for y, old, _ in periodi_confronto:
            for titolo, keys, levels, skip in alberature:
                df = rbm.flatten_hierarchical_table(
                    aggm.aggregate_hierarchical_custom(cur, keys, skip),
                    aggm.aggregate_hierarchical_custom(old, keys, skip), levels)
                out.append((f"{titolo} — {y_curr} vs {y}",
                            df.drop(columns="Depth", errors="ignore")))

    elif tipo == "y2y_codici":
        for y, old, _ in periodi_confronto:
            out.append((f"Comparativa Codici (SKU7) — {y_curr} vs {y}",
                        rbm.comparativa_codici(cur, old, pipe.anagrafica, y_curr, y)))

    elif tipo == "taglie":
        def _taglie_uno(df: pd.DataFrame) -> pd.DataFrame:
            pezzi = []
            for brand, gruppi in rbm.taglie_tables(df).items():
                for gruppo, d0 in gruppi.items():
                    d = d0.copy()
                    d.insert(0, "Brand", brand)
                    d.insert(1, "Gruppo", gruppo)
                    pezzi.append(d)
            vuota = pd.DataFrame(columns=["Brand", "Gruppo", "Taglia", "Paia Nette",
                                          "% su gruppo", "% Reso", "Fatturato Netto"])
            return pd.concat(pezzi, ignore_index=True) if pezzi else vuota
        out.append((f"Taglie per Brand — {y_curr}", _taglie_uno(cur)))
        for y, old, _ in periodi_confronto:
            out.append((f"Taglie per Brand — {y}", _taglie_uno(old)))

    elif tipo == "resi":
        out.append((f"Stato Resi per Brand/Collezione — {y_curr}", rbm.resi_status(cur)))
        for y, old, _ in periodi_confronto:
            out.append((f"Stato Resi per Brand/Collezione — {y}", rbm.resi_status(old)))

    elif tipo == "nazioni":
        dfs = [cur] + [old for _, old, _ in periodi_confronto]
        naz = nazioni or (["GLOBAL"] + rbm.nazioni_disponibili(*dfs))
        if naz:
            out.append((f"KPI per nazione — {y_curr}", rbm.nazioni_metrics(cur, sc, naz)))
            for y, old, so in periodi_confronto:
                out.append((f"KPI per nazione — {y}", rbm.nazioni_metrics(old, so, naz)))
            for n in naz:
                out.append((f"Share brand — {n} — {y_curr}", rbm.nazioni_brand_share(cur, n)))
                for y, old, _ in periodi_confronto:
                    out.append((f"Share brand — {n} — {y}", rbm.nazioni_brand_share(old, n)))

    elif tipo == "mensile":
        # report "Mese per Mese": mesi dal mese di `da` al mese di `a` (finestra mobile,
        # NON gennaio→dicembre), con stagioni SS (mar–ago) / FW (set–feb) e confronti
        # anno-1/anno-2 come per gli altri report (confronti=0 → solo periodo scelto).
        periodi = [(y_curr, cur, sc)] + list(periodi_confronto)
        df_mesi, df_stagioni = rbm.monthly_season_report(da, a, periodi)
        out.append((f"Andamento Mese per Mese — {y_curr}", df_mesi))
        out.append((f"Statistiche Stagioni SS/FW — {y_curr}", df_stagioni))

    elif tipo == "unificato":
        periodi = [(y_curr, cur)] + [(y, old) for y, old, _ in periodi_confronto]
        dfs = [cur] + [old for _, old, _ in periodi_confronto]
        naz = nazioni or rbm.nazioni_disponibili(*dfs)
        if naz:
            out.append(("Report Unificato — Marketplace × Nazione × Brand",
                        rbm.nazioni_unified_report(periodi, naz)))
    return out


def _rispondi_report(sezioni: list[tuple[str, pd.DataFrame]], fmt: str, parametri: dict,
                    nome: str, download: bool = False) -> Response:
    if not sezioni:
        if fmt == "json":
            return JSONResponse({"ok": True, "parametri": parametri, "tabelle": []})
        return Response(f"{nome}: nessun dato per i parametri richiesti.",
                         media_type="text/plain; charset=utf-8")
    if fmt == "json":
        return JSONResponse({"ok": True, "parametri": parametri,
                             "tabelle": [{"titolo": t, "righe": int(len(d)),
                                          "colonne": [_RENAME_COLONNE.get(c, c) for c in d.columns],
                                          "dati": _records(d.rename(columns=_RENAME_COLONNE))}
                                         for t, d in sezioni]})
    sezioni = [(t, _pretty_df(_date_leggibili(d))) for t, d in sezioni]
    if fmt == "csv":
        if len(sezioni) == 1:
            corpo = sezioni[0][1].to_csv(index=False, lineterminator="\n")
        else:  # tabelle con colonne diverse: colonna Sezione + unione delle colonne
            corpo = pd.concat([d.assign(Sezione=t) for t, d in sezioni],
                              ignore_index=True).to_csv(index=False, lineterminator="\n")
        media = "text/csv; charset=utf-8"
    elif fmt == "md":
        corpo = f"# {nome}\n\n"
        for t, d in sezioni:
            corpo += f"## {t}\n\n" + _df_md(d) + "\n\n"
        media = "text/markdown; charset=utf-8"
    else:  # txt
        corpo = "\n\n".join(f"=== {t} ===\n" + d.to_string(index=False)
                            for t, d in sezioni)
        media = "text/plain; charset=utf-8"
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{nome}.{fmt}"'
    return Response(corpo, media_type=media, headers=headers)


@app.get("/api/v1/report")
def report(
    tipo: str = Query(..., description="Report da estrarre",
                      pattern="^(" + "|".join(_TIPI_REPORT) + ")$"),
    # NB: da/a con Query(...) restano OBBLIGATORI (per FastAPI "..." = required),
    # ma danno a Python un default formale: senza, "parameter without a default
    # follows parameter with a default" perché tipo=... viene prima.
    da: date = Query(..., description="Inizio periodo scelto, YYYY-MM-DD"),
    a: date = Query(..., description="Fine periodo scelto, YYYY-MM-DD"),
    confronti: int = Query(0, ge=0, le=2,
                           description="Anni di confronto: 0 = solo periodo scelto; "
                                       "1 = + anno-1; 2 = + anno-1 e anno-2 (massimo 2)"),
    perimetro: str = Query("1", pattern="^[123]$"),
    dim: str = Query("mkp", pattern="^(mkp|nazione|brand)$"),
    top: int = Query(50, ge=1, le=100, description="Top articoli: max 100"),
    nazioni: str | None = None,
    fmt: str = Query("md", alias="format", pattern="^(json|csv|md|txt)$"),
    mkp: str | None = None, nazione: str | None = None, brand: str | None = None,
    sku: str | None = None, genere: str | None = None, taglia: str | None = None,
    acquirente: str | None = None,
    download: bool = False,
    ident: dict = Depends(require_auth),
) -> Response:
    """Estrae uno dei report dell'app, con le stesse identiche tabelle e cifre.

    Periodi (a richiesta, parametro `confronti`):
      - 0 (default) → solo il periodo scelto [da, a];
      - 1 → aggiunge il periodo−1 anno; 2 → aggiunge anche il periodo−2 anno;
      - valori fuori 0–2 → 422 (validazione automatica). I tipi y2y_* sono
        comparativi per natura: con confronti=0 rispondono 400. Il tipo `mensile`
        (Andamento Mese per Mese con stagioni SS/FW) accetta anche confronti=0.
    Etichette anno ovunque = anno della DATA FINALE del periodo scelto e i
    relativi -1/-2 (es. a=2026-06-30 → "2026", "2025", "2024").
    Formato default: md; json per elaborazioni, csv/txt per Excel.
    """
    _check_periodo(da, a)
    if confronti == 0 and tipo.startswith("y2y"):
        raise HTTPException(400, "i report y2y_* sono comparativi per natura: "
                                 "usa confronti=1 (anno-1) o confronti=2 (anno-1 + anno-2)")
    y_curr = str(a.year)
    anni_confronto = [str(a.year - i) for i in range(1, confronti + 1)]   # ["2025"] o ["2025", "2024"]

    filtri = _filtri_comuni(mkp, nazione, brand, sku, genere, taglia, acquirente)
    m_filtri = _mappa_filtri(filtri)
    naz = ([s.strip().upper() for s in nazioni.split(",") if s.strip()]
           if nazioni else None)

    # periodo scelto (+ anno-1 nella pipeline se richiesto); anno-2 interrogato a parte
    p1 = (_shift_year(da, -1), _shift_year(a, -1))
    pipe = _build_pipe(da, a, p1 if confronti >= 1 else None, perimetro)
    if filtri:
        _filtra_report(pipe, filtri)

    periodi_confronto: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []  # (anno, vendite, rimborsi)
    non_coperti: list[str] = []
    if confronti >= 1:
        if not pipe.old_data.empty:                     # anno-1
            periodi_confronto.append((anni_confronto[0], pipe.old_data,
                                       pipe.esito_resi_old["standalone"]))
        else:
            non_coperti.append(f"{anni_confronto[0]} (anno-1)")
    if confronti == 2:
        data_2, s2 = _apri_e_query(_shift_year(da, -2), _shift_year(a, -2), perimetro)
        if filtri:
            data_2 = _filtra(data_2, **m_filtri)
            s2 = _filtra(s2, **m_filtri)
        if not data_2.empty:                            # anno-2
            periodi_confronto.append((anni_confronto[1], data_2, s2))
        else:
            non_coperti.append(f"{anni_confronto[1]} (anno-2)")

    sezioni = [(t, d) for t, d in _sezioni_report(tipo, pipe, y_curr, dim, top, naz,
                                                  periodi_confronto, da, a)
               if d is not None and not d.empty]
    parametri = {"tipo": tipo, "da": str(da), "a": str(a), "perimetro": perimetro,
                 "confronti": confronti,
                 "anni": {"corrente": y_curr, "confronto": anni_confronto},
                 "dim": dim, "top": top, "nazioni": naz, "filtri": filtri}
    if non_coperti:
        parametri["avviso"] = ("Periodi di confronto non coperti dal DB: "
                               + ", ".join(non_coperti)
                               + " — il report mostra solo gli anni con dati.")
    return _rispondi_report(sezioni, fmt, parametri, f"report_{tipo}_{da}_{a}", download)


# ---------------------------------------------------------------------------------------
# Frontend SPA (build React, senza nginx): la stessa uvicorn serve anche le statiche
# ---------------------------------------------------------------------------------------
# Il progetto frontend puo' vivere in una directory qualsiasi, anche fuori dal repo:
# la posizione della build si configura con la variabile d'ambiente EA_FRONTEND_DIR
# (default: <root>/frontend/dist, dove <root> e' la directory che contiene api/).
# Con la build presente l'app risponde cosi':
#   /api/v1/...           → API (rotte esistenti, nessuna modifica)
#   /assets/...           → bundle JS/CSS di Vite
#   /  /y2y  /nazioni ... → index.html (SPA routing lato client)
# Senza build presente l'API funziona esattamente come prima (solo /api).
# Le chiamate /api/* sconosciute restano API: 404 JSON, non index.html.
from fastapi.responses import FileResponse as _FileResponse
from fastapi.staticfiles import StaticFiles as _StaticFiles

_FRONTEND_DIR = Path(os.environ.get(
    "EA_FRONTEND_DIR", str(Path(__file__).resolve().parents[1] / "frontend" / "dist")))

if _FRONTEND_DIR.is_dir() and (_FRONTEND_DIR / "index.html").is_file():
    _ASSETS = _FRONTEND_DIR / "assets"
    if _ASSETS.is_dir():
        app.mount("/assets", _StaticFiles(directory=str(_ASSETS)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Fallback: file statico se esiste, altrimenti index.html (SPA)."""
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "Endpoint non trovato.")
        candidato = (_FRONTEND_DIR / full_path).resolve()
        radice = _FRONTEND_DIR.resolve()
        if full_path and candidato.is_file() and str(candidato).startswith(str(radice)):
            return _FileResponse(str(candidato))
        return _FileResponse(str(_FRONTEND_DIR / "index.html"))