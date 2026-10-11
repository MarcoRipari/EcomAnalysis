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

COLONNE = ["Anno", "Mese", "Scope", "Marketplace", "Nazione", "Brand", "Fatturato", "Share %",
           "Valore Medio Paio", "Paia spedite", "Paia rese", "Paia nette", "Reso %",
           "Reso % (valore)", "Var % Fatturato YoY"]

MESE_TOTALE = "Tutto il periodo"


def _prepara(venduto: pd.DataFrame | None, resi_fp: pd.DataFrame | None) -> pd.DataFrame:
    """Unisce venduto e resi fuori periodo in un solo frame con le dimensioni e il mese."""
    pezzi = []
    for df, col_data in ((venduto, "dataVendita"), (resi_fp, "dataReso")):
        if df is None or df.empty:
            continue
        w = pd.DataFrame({
            "mkp": df["mkp"].astype(str).to_numpy(),
            "nazione": df["nazione"].astype(str).to_numpy(),
            "brand": df["clzMappata"].astype(str).replace("", "ALTRO").to_numpy(),
            "mese": pd.to_datetime(df[col_data], errors="coerce").dt.month.fillna(0).astype(int).to_numpy(),
        })
        for m in _MISURE:
            w[m] = df[m].astype(float).to_numpy()
        pezzi.append(w)
    if not pezzi:
        return pd.DataFrame(columns=["mkp", "nazione", "brand", "mese"] + _MISURE)
    return pd.concat(pezzi, ignore_index=True)


def _righe_fetta(w: pd.DataFrame, anno: str, mese: str, nazioni: set[str]) -> list[dict]:
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
                "Anno": anno, "Mese": mese, "Scope": scope,
                "Marketplace": dim.get("mkp", "GLOBAL"), "Nazione": naz,
                "Brand": dim.get("brand", "GLOBAL"),
                "Fatturato": fatt,
                "Share %": fatt / tot if tot != 0 else 0.0,
                "Valore Medio Paio": fatt / nette if nette > 0 else 0.0,
                "Paia spedite": sped, "Paia rese": rese, "Paia nette": nette,
                "Reso %": rese / sped if sped > 0 else 0.0,
                "Reso % (valore)": float(k["nettoReso"]) / f_sped if f_sped > 0 else 0.0,
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
    """`periodi` = [(etichetta anno, venduto, resi_fuori_periodo), …] dal più recente al più vecchio.
    Con `mensile` una riga per ogni mese del periodo, altrimenti Mese = "Tutto il periodo"."""
    nazioni = set(nazioni_scelte or [])
    rows: list[dict] = []
    for label, venduto, resi_fp in periodi:
        w = _prepara(venduto, resi_fp)
        if w.empty:
            continue
        if mensile:
            for m in sorted(w["mese"].unique()):
                if m >= 1:
                    rows += _righe_fetta(w[w["mese"] == m], label, CFG.MESI_IT[m - 1], nazioni)
        else:
            rows += _righe_fetta(w, label, MESE_TOTALE, nazioni)
    if not rows:
        return pd.DataFrame(columns=COLONNE)

    out = pd.DataFrame(rows)

    # Var % YoY: stessa fetta (mese, scope, dimensioni) del periodo successivo nell'elenco
    etichette = [p[0] for p in periodi]
    chiave = ["Mese", "Scope", "Marketplace", "Nazione", "Brand"]
    chiavi = list(out[chiave].itertuples(index=False, name=None))
    lookup = {(a, *k): f for a, k, f in zip(out["Anno"], chiavi, out["Fatturato"])}
    var = []
    for a, k, f in zip(out["Anno"], chiavi, out["Fatturato"]):
        i = etichette.index(a)
        prev = lookup.get((etichette[i + 1], *k)) if i + 1 < len(etichette) else None
        if prev is None:
            var.append(None)
        else:
            var.append((f / prev - 1) if prev != 0 else (1.0 if f > 0 else 0.0))
    out["Var % Fatturato YoY"] = var

    ordine_anno = {a: i for i, a in enumerate(etichette)}
    ordine_scope = {s: i for i, s in enumerate(SCOPES)}
    ordine_mese = {m: i for i, m in enumerate([MESE_TOTALE] + CFG.MESI_IT)}
    out["_a"] = out["Anno"].map(ordine_anno)
    out["_m"] = out["Mese"].map(ordine_mese)
    out["_s"] = out["Scope"].map(ordine_scope)
    out = out.sort_values(["_a", "_m", "_s", "Fatturato"], ascending=[True, True, True, False],
                          kind="mergesort")
    return out.drop(columns=["_a", "_m", "_s"])[COLONNE].reset_index(drop=True)


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
