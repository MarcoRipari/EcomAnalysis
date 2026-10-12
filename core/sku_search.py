"""
Trova SKU — analisi dettagliata di uno SKU (anche parziale: 7, 9 o 13 caratteri).

Le cifre sono quelle del resto dell'app: il venduto e i resi fuori periodo arrivano da
db.query_period e i KPI da metrics.kpi_reali, quindi il Fatturato di ogni tabella
somma esattamente al totale dello SKU cercato.

"Intero DB" = periodo che copre qualunque data (FULL_DB_PERIOD): la regola dei resi
(un reso conta nel venduto solo se la sua data è nello stesso periodo) vale come sempre,
e con un periodo illimitato tutti i resi sono "del periodo".
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date

import numpy as np
import pandas as pd

from . import db as dbmod
from . import metrics as met

FULL_DB_PERIOD = (date(1900, 1, 1), date(2100, 12, 31))
LUNGHEZZE_CONSIGLIATE = (7, 9, 13)

_MISURE = ["nettoNetto", "nettoSpedito", "nettoReso", "paiaSpedite", "paiaRese", "paiaNette"]


def normalizza_sku(testo: str) -> str:
    """Solo lettere e cifre, maiuscolo: 'abc-1234 56' → 'ABC123456' (i trattini non fanno parte dello SKU)."""
    return re.sub(r"[^A-Za-z0-9]", "", testo or "").upper()


def cerca(conn: sqlite3.Connection, prefisso: str, periodo: tuple, perimetro: str = "1"
          ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(venduto, resi_fuori_periodo) degli SKU che iniziano per `prefisso` nel `periodo`."""
    return dbmod.query_period(conn, periodo[0], periodo[1], perimetro, sku_prefix=normalizza_sku(prefisso))


def _unisci(venduto: pd.DataFrame | None, resi_fp: pd.DataFrame | None) -> pd.DataFrame:
    """Venduto + resi in un solo frame.
    Le vendite vanno al mese di dataVendita; i resi (sia del venduto nel periodo,
    sia fuori periodo) vanno al mese di dataReso."""
    pezzi = []
    if venduto is not None and not venduto.empty:
        # 1. Vendite
        v_sales = venduto.copy()
        mese_v = pd.to_datetime(v_sales["dataVendita"], errors="coerce").dt.strftime("%Y-%m").fillna("n.d.").to_numpy()
        w_sales = pd.DataFrame({
            "Marketplace": v_sales["mkp"].astype(str).to_numpy(),
            "Nazione": v_sales["nazione"].astype(str).to_numpy(),
            "Taglia": v_sales["taglia"].astype(str).to_numpy(),
            "Canale": v_sales["tipoSpedizione"].astype(str).to_numpy(),
            "SKU": v_sales["sku13"].astype(str).to_numpy(),
            "Mese": mese_v,
            "nettoNetto": v_sales["nettoSpedito"].astype(float).to_numpy(),
            "nettoSpedito": v_sales["nettoSpedito"].astype(float).to_numpy(),
            "nettoReso": np.zeros(len(v_sales), dtype=float),
            "paiaSpedite": v_sales["paiaSpedite"].astype(float).to_numpy(),
            "paiaRese": np.zeros(len(v_sales), dtype=float),
            "paiaNette": v_sales["paiaSpedite"].astype(float).to_numpy(),
        })
        pezzi.append(w_sales)

        # 2. Resi del venduto
        v_resi = venduto[venduto["isReso"] & venduto["dataReso"].notna()].copy()
        if not v_resi.empty:
            mese_r = pd.to_datetime(v_resi["dataReso"], errors="coerce").dt.strftime("%Y-%m").fillna("n.d.").to_numpy()
            n_r = v_resi["nettoReso"].astype(float).to_numpy()
            p_r = v_resi["paiaRese"].astype(float).to_numpy()
            w_resi = pd.DataFrame({
                "Marketplace": v_resi["mkp"].astype(str).to_numpy(),
                "Nazione": v_resi["nazione"].astype(str).to_numpy(),
                "Taglia": v_resi["taglia"].astype(str).to_numpy(),
                "Canale": v_resi["tipoSpedizione"].astype(str).to_numpy(),
                "SKU": v_resi["sku13"].astype(str).to_numpy(),
                "Mese": mese_r,
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
        mese_fp = pd.to_datetime(resi_fp[col_d], errors="coerce").dt.strftime("%Y-%m").fillna("n.d.").to_numpy()
        w_fp = pd.DataFrame({
            "Marketplace": resi_fp["mkp"].astype(str).to_numpy(),
            "Nazione": resi_fp["nazione"].astype(str).to_numpy(),
            "Taglia": resi_fp["taglia"].astype(str).to_numpy(),
            "Canale": resi_fp["tipoSpedizione"].astype(str).to_numpy(),
            "SKU": resi_fp["sku13"].astype(str).to_numpy(),
            "Mese": mese_fp,
        })
        for m in _MISURE:
            w_fp[m] = resi_fp[m].astype(float).to_numpy()
        pezzi.append(w_fp)

    if not pezzi:
        return pd.DataFrame(columns=["Marketplace", "Nazione", "Taglia", "Canale", "SKU", "Mese"] + _MISURE)
    return pd.concat(pezzi, ignore_index=True)


COLONNE_TABELLA = ["Fatturato", "Share %", "Valore Medio Paio", "Paia spedite", "Paia rese",
                   "Paia nette", "% Reso"]


def tabella_per(venduto: pd.DataFrame, resi_fp: pd.DataFrame, dimensione: str) -> pd.DataFrame:
    """Una riga per valore di `dimensione` (Marketplace, Nazione, Taglia, Canale, SKU, Mese).
    Fatturato include i resi fuori periodo: la somma della colonna è il totale dello SKU."""
    w = _unisci(venduto, resi_fp)
    if w.empty:
        return pd.DataFrame(columns=[dimensione] + COLONNE_TABELLA)
    g = w.groupby(dimensione, sort=False, observed=True)[_MISURE].sum().reset_index()
    g["paiaNette"] = g["paiaNette"].clip(lower=0)               # mai negative (solo resi fuori periodo)
    tot = float(g["nettoNetto"].sum())
    out = pd.DataFrame({
        dimensione: g[dimensione],
        "Fatturato": g["nettoNetto"],
        "Share %": g["nettoNetto"] / tot if tot != 0 else 0.0,
        "Valore Medio Paio": (g["nettoNetto"] / g["paiaNette"]).where(g["paiaNette"] > 0, 0.0),
        "Paia spedite": g["paiaSpedite"], "Paia rese": g["paiaRese"], "Paia nette": g["paiaNette"],
        "% Reso": (g["paiaRese"] / g["paiaSpedite"]).where(g["paiaSpedite"] > 0, 0.0),
    })
    return out


def per_taglia(venduto: pd.DataFrame, resi_fp: pd.DataFrame) -> pd.DataFrame:
    """Per taglia, in ordine di taglia (numeriche crescenti, poi lettere/UNICA/ND)."""
    t = tabella_per(venduto, resi_fp, "Taglia")
    if t.empty:
        return t
    def chiave(x: str):
        m = re.match(r"^(\d+)", x)
        return (0, int(m.group(1)), x) if m else (1, 0, x)
    return t.iloc[sorted(range(len(t)), key=lambda i: chiave(str(t["Taglia"].iloc[i])))].reset_index(drop=True)


def per_mese(venduto: pd.DataFrame, resi_fp: pd.DataFrame) -> pd.DataFrame:
    t = tabella_per(venduto, resi_fp, "Mese")
    return t.sort_values("Mese").reset_index(drop=True) if not t.empty else t


def per_dimensione(venduto: pd.DataFrame, resi_fp: pd.DataFrame, dimensione: str) -> pd.DataFrame:
    t = tabella_per(venduto, resi_fp, dimensione)
    return t.sort_values("Fatturato", ascending=False).reset_index(drop=True) if not t.empty else t


def date_vendita(venduto: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if venduto is None or venduto.empty:
        return None, None
    d = venduto["dataVendita"].dropna()
    return (d.min(), d.max()) if not d.empty else (None, None)


def percentuale_promo(venduto: pd.DataFrame) -> float:
    """Quota di paia spedite vendute in promozione."""
    if venduto is None or venduto.empty:
        return 0.0
    tot = float(venduto["paiaSpedite"].sum())
    return float(venduto.loc[venduto["isPromo"], "paiaSpedite"].sum()) / tot if tot > 0 else 0.0


def articoli_trovati(venduto: pd.DataFrame, resi_fp: pd.DataFrame, anagrafica: dict) -> pd.DataFrame:
    """Una riga per SKU13 trovato, con descrizione dall'anagrafica e i principali numeri."""
    t = tabella_per(venduto, resi_fp, "SKU")
    if t.empty:
        return t
    t = t.sort_values("Fatturato", ascending=False).reset_index(drop=True)
    t.insert(1, "Descrizione", [anagrafica.get(s, {}).get("desc") or anagrafica.get(s[:7], {}).get("desc", "-")
                                for s in t["SKU"]])
    return t


def dettaglio_righe(venduto: pd.DataFrame, resi_fp: pd.DataFrame) -> pd.DataFrame:
    """Elenco delle singole righe (venduto + resi fuori periodo) per consultazione ed export."""
    pezzi = []
    for df, tipo in ((venduto, "Venduto"), (resi_fp, "Reso fuori periodo")):
        if df is None or df.empty:
            continue
        pezzi.append(pd.DataFrame({
            "Tipo": tipo,
            "Data vendita": pd.to_datetime(df["dataVendita"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("").to_numpy(),
            "Data reso": pd.to_datetime(df["dataReso"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("").to_numpy(),
            "Ordine": df["ordineId"].astype(str).to_numpy(),
            "Marketplace": df["mkp"].astype(str).to_numpy(),
            "Nazione": df["nazione"].astype(str).to_numpy(),
            "SKU": df["skuFull"].astype(str).to_numpy(),
            "Taglia": df["taglia"].astype(str).to_numpy(),
            "Paia spedite": df["paiaSpedite"].astype(float).to_numpy(),
            "Paia rese": df["paiaRese"].astype(float).to_numpy(),
            "Fatturato": df["nettoNetto"].astype(float).to_numpy(),
        }))
    if not pezzi:
        return pd.DataFrame()
    return pd.concat(pezzi, ignore_index=True).sort_values(["Data vendita", "Ordine"]).reset_index(drop=True)


def kpi(venduto: pd.DataFrame, resi_fp: pd.DataFrame) -> dict:
    return met.kpi_reali(venduto, resi_fp)
