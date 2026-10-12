"""
Export massivo (CSV / Markdown) raggruppato per SCOPE.

Ogni riga è una fetta di dati (Anno × Mese × Marketplace × Nazione × Brand) con lo stesso
Fatturato usato dalle pagine (core.metrics): venduto + resi fuori periodo.
La somma delle righe di ogni SCOPE (con tutte le nazioni del periodo selezionate) coincide
con la riga GLOBAL: nessuna combinazione presente solo nei resi fuori periodo va persa.

Attribuzione ai mesi: il venduto va al mese della Data Pagamento (compresi i resi del periodo
sulla stessa riga); i resi fuori periodo vanno al mese della Data Reso.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as CFG

SCOPES = ["DETAIL", "MARKETPLACE_COUNTRY", "MARKETPLACE_BRAND", "COUNTRY_BRAND",
          "GLOBAL_MARKETPLACE", "GLOBAL_COUNTRY", "GLOBAL_BRAND", "GLOBAL"]

# scope → dimensioni di raggruppamento (le dimensioni assenti valgono "GLOBAL")
_SCOPE_KEYS = {
    "DETAIL": ["mkp", "nazione", "brand"],
    "MARKETPLACE_COUNTRY": ["mkp", "nazione"],
    "MARKETPLACE_BRAND": ["mkp", "brand"],
    "COUNTRY_BRAND": ["nazione", "brand"],
    "GLOBAL_MARKETPLACE": ["mkp"],
    "GLOBAL_COUNTRY": ["nazione"],
    "GLOBAL_BRAND": ["brand"],
    "GLOBAL": [],
}
_MISURE = ["nettoNetto", "nettoSpedito", "nettoReso", "paiaSpedite", "paiaRese", "paiaNette"]

COLONNE = ["Periodo", "Anno", "Mese", "Scope", "Marketplace", "Nazione", "Brand", "Fatturato", "Share %",
           "Valore Medio Paio", "Paia spedite", "Paia rese", "Paia nette", "Reso %",
           "Reso % (valore)", "Var % Fatturato YoY"]

MESE_TOTALE = "Tutto il periodo"


def _prepara(venduto: pd.DataFrame | None, resi_fp: pd.DataFrame | None) -> pd.DataFrame:
    """Unisce venduto e resi in un solo frame.
    Le vendite vanno alla data di vendita; i resi (sia del venduto con dataReso nel periodo,
    sia fuori periodo) vanno alla data di reso.
    Ogni riga conserva sia 'anno' (anno solare effettivo: 2024, 2025, 2026) sia 'mese' (1..12)."""
    pezzi = []
    if venduto is not None and not venduto.empty:
        # 1. Vendite
        v_sales = venduto.copy()
        dt_v = pd.to_datetime(v_sales["dataVendita"], errors="coerce")
        anno_v = dt_v.dt.year.fillna(0).astype(int).to_numpy()
        mese_v = dt_v.dt.month.fillna(0).astype(int).to_numpy()
        w_sales = pd.DataFrame({
            "mkp": v_sales["mkp"].astype(str).to_numpy(),
            "nazione": v_sales["nazione"].astype(str).to_numpy(),
            "brand": v_sales["clzMappata"].astype(str).replace("", "ALTRO").to_numpy(),
            "anno": anno_v,
            "mese": mese_v,
            "nettoNetto": v_sales["nettoSpedito"].astype(float).to_numpy(),
            "nettoSpedito": v_sales["nettoSpedito"].astype(float).to_numpy(),
            "nettoReso": np.zeros(len(v_sales), dtype=float),
            "paiaSpedite": v_sales["paiaSpedite"].astype(float).to_numpy(),
            "paiaRese": np.zeros(len(v_sales), dtype=float),
            "paiaNette": v_sales["paiaSpedite"].astype(float).to_numpy(),
        })
        pezzi.append(w_sales)

        # 2. Resi del venduto (solo se effettivamente resi nel periodo)
        v_resi = venduto[venduto["isReso"] & venduto["dataReso"].notna()].copy()
        if not v_resi.empty:
            dt_r = pd.to_datetime(v_resi["dataReso"], errors="coerce")
            anno_r = dt_r.dt.year.fillna(0).astype(int).to_numpy()
            mese_r = dt_r.dt.month.fillna(0).astype(int).to_numpy()
            n_r = v_resi["nettoReso"].astype(float).to_numpy()
            p_r = v_resi["paiaRese"].astype(float).to_numpy()
            w_resi = pd.DataFrame({
                "mkp": v_resi["mkp"].astype(str).to_numpy(),
                "nazione": v_resi["nazione"].astype(str).to_numpy(),
                "brand": v_resi["clzMappata"].astype(str).replace("", "ALTRO").to_numpy(),
                "anno": anno_r,
                "mese": mese_r,
                "nettoNetto": -n_r,
                "nettoSpedito": np.zeros(len(v_resi), dtype=float),
                "nettoReso": n_r,
                "paiaSpedite": np.zeros(len(v_resi), dtype=float),
                "paiaRese": p_r,
                "paiaNette": -p_r,
            })
            pezzi.append(w_resi)

    # 3. Resi fuori periodo
    if resi_fp is not None and not resi_fp.empty:
        col_d = "dataReso" if "dataReso" in resi_fp.columns else "dataVendita"
        dt_fp = pd.to_datetime(resi_fp[col_d], errors="coerce")
        anno_fp = dt_fp.dt.year.fillna(0).astype(int).to_numpy()
        mese_fp = dt_fp.dt.month.fillna(0).astype(int).to_numpy()
        w_fp = pd.DataFrame({
            "mkp": resi_fp["mkp"].astype(str).to_numpy(),
            "nazione": resi_fp["nazione"].astype(str).to_numpy(),
            "brand": resi_fp["clzMappata"].astype(str).replace("", "ALTRO").to_numpy(),
            "anno": anno_fp,
            "mese": mese_fp,
        })
        for m in _MISURE:
            w_fp[m] = resi_fp[m].astype(float).to_numpy()
        pezzi.append(w_fp)

    if not pezzi:
        return pd.DataFrame(columns=["mkp", "nazione", "brand", "anno", "mese"] + _MISURE)
    return pd.concat(pezzi, ignore_index=True)


def _righe_fetta(w: pd.DataFrame, periodo: str, anno: str, mese: str, nazioni: set[str],
                 seq: int = 0) -> list[dict]:
    tot = float(w["nettoNetto"].sum())
    out = []
    for scope in SCOPES:
        keys = _SCOPE_KEYS[scope]
        if keys:
            g = w.groupby(keys, sort=False, observed=True)[_MISURE].sum()
        else:
            g = w[_MISURE].sum().to_frame().T
        for idx, k in g.iterrows():
            idx = idx if isinstance(idx, tuple) else (idx,)
            dim = dict(zip(keys, idx))
            naz = dim.get("nazione", "GLOBAL")
            if "nazione" in keys and naz not in nazioni:
                continue
            fatt, sped, rese = float(k["nettoNetto"]), float(k["paiaSpedite"]), float(k["paiaRese"])
            nette, f_sped = max(0.0, float(k["paiaNette"])), float(k["nettoSpedito"])
            out.append({
                "Periodo": periodo, "Anno": str(anno), "Mese": mese, "Scope": scope,
                "Marketplace": dim.get("mkp", "GLOBAL"), "Nazione": naz,
                "Brand": dim.get("brand", "GLOBAL"),
                "Fatturato": fatt,
                "Share %": fatt / tot if tot != 0 else 0.0,
                "Valore Medio Paio": fatt / nette if nette > 0 else 0.0,
                "Paia spedite": sped, "Paia rese": rese, "Paia nette": nette,
                "Reso %": rese / sped if sped > 0 else 0.0,
                "Reso % (valore)": float(k["nettoReso"]) / f_sped if f_sped > 0 else 0.0,
                "_seq": seq,
            })
    return out


def nazioni_disponibili(periodi: list[tuple]) -> list[str]:
    """Nazioni presenti in almeno un periodo (venduto o resi fuori periodo), ordinate."""
    naz: set[str] = set()
    for _, venduto, resi_fp in periodi:
        for df in (venduto, resi_fp):
            if df is not None and not df.empty:
                naz |= set(df["nazione"].astype(str).unique())
    return sorted(n for n in naz if n)


def build_export(periodi: list[tuple], nazioni_scelte: list[str], mensile: bool = False) -> pd.DataFrame:
    """`periodi` = [(etichetta periodo, venduto, resi_fuori_periodo), …] dal più recente al più vecchio.
    Con `mensile` una riga per ogni mese del periodo in ordine cronologico,
    altrimenti Mese = "Tutto il periodo"."""
    nazioni = set(nazioni_scelte or [])
    rows: list[dict] = []
    for label, venduto, resi_fp in periodi:
        w = _prepara(venduto, resi_fp)
        if w.empty:
            continue
        if mensile:
            ym_validi = sorted({(int(y), int(m)) for y, m in zip(w["anno"], w["mese"]) if y > 0 and 1 <= m <= 12})
            for seq_idx, (y, m) in enumerate(ym_validi):
                w_sub = w[(w["anno"] == y) & (w["mese"] == m)]
                rows += _righe_fetta(w_sub, label, str(y), CFG.MESI_IT[m - 1], nazioni, seq=seq_idx)
        else:
            anni = sorted({int(y) for y in w["anno"] if y > 0})
            if len(anni) > 1:
                anno_str = f"{anni[0]}-{anni[-1]}"
            elif len(anni) == 1:
                anno_str = str(anni[0])
            else:
                anno_str = str(label)
            rows += _righe_fetta(w, label, anno_str, MESE_TOTALE, nazioni, seq=0)
    if not rows:
        return pd.DataFrame(columns=COLONNE)

    out = pd.DataFrame(rows)

    # Var % YoY: stessa fetta (mese, scope, dimensioni) del periodo successivo nell'elenco
    etichette = [p[0] for p in periodi]
    chiave = ["Mese", "Scope", "Marketplace", "Nazione", "Brand"]
    chiavi = list(out[chiave].itertuples(index=False, name=None))
    lookup = {(p, *k): f for p, k, f in zip(out["Periodo"], chiavi, out["Fatturato"])}
    var = []
    for p, k, f in zip(out["Periodo"], chiavi, out["Fatturato"]):
        i = etichette.index(p)
        prev = lookup.get((etichette[i + 1], *k)) if i + 1 < len(etichette) else None
        if prev is None:
            var.append(None)
        else:
            var.append((f / prev - 1) if prev != 0 else (1.0 if f > 0 else 0.0))
    out["Var % Fatturato YoY"] = var

    ordine_periodo = {p: i for i, p in enumerate(etichette)}
    ordine_scope = {s: i for i, s in enumerate(SCOPES)}
    out["_p"] = out["Periodo"].map(ordine_periodo)
    out["_s"] = out["Scope"].map(ordine_scope)
    out = out.sort_values(["_p", "_seq", "_s", "Fatturato"], ascending=[True, True, True, False],
                          kind="mergesort")
    return out.drop(columns=["_p", "_seq", "_s"])[COLONNE].reset_index(drop=True)


PERCENTUALI = {"Share %", "Reso %", "Reso % (valore)", "Var % Fatturato YoY"}


def to_csv(df: pd.DataFrame) -> bytes:
    """CSV per Excel italiano: separatore ';', virgola decimale, UTF-8 con BOM.
    Le colonne "%" sono in punti percentuali (22,34 = 22,34%), come nel Markdown."""
    out = df.copy()
    for c in PERCENTUALI & set(out.columns):
        out[c] = out[c] * 100
    return out.to_csv(index=False, sep=";", decimal=",", float_format="%.4f").encode("utf-8-sig")


def _num(x: float, dec: int = 2) -> str:
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def to_markdown(df: pd.DataFrame) -> str:
    """Tabella Markdown con numeri in formato italiano (1.234,56) e percentuali con 1 decimale."""
    perc = PERCENTUALI
    interi = {"Paia spedite", "Paia rese", "Paia nette"}
    righe = ["| " + " | ".join(df.columns) + " |", "|" + "|".join("---" for _ in df.columns) + "|"]
    for r in df.itertuples(index=False, name=None):
        celle = []
        for c, v in zip(df.columns, r):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                celle.append("")
            elif c in perc:
                celle.append(_num(v * 100, 1) + "%")
            elif c in interi:
                celle.append(_num(v, 0))
            elif isinstance(v, float):
                celle.append(_num(v, 2))
            else:
                celle.append(str(v))
        righe.append("| " + " | ".join(celle) + " |")
    return "\n".join(righe)
