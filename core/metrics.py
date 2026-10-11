"""
Metriche globali e KPI — UNICA definizione dei numeri mostrati da app, API ed export.

Terminologia (vale per tutto il progetto):
- *venduto*: righe con Data Pagamento nel periodo. Un reso conta nel venduto solo se la sua
  Data Reso cade nello stesso periodo; altrimenti la riga resta SPEDITA.
- *resi fuori periodo*: resi con Data Reso nel periodo ma vendita fuori dal periodo. Un reso
  caricato prima del suo ordine è un ordine reale (ha la sua Data Pagamento): segue le stesse
  regole di tutti gli altri.
  Vivono in un DataFrame a parte, con valori già negativi (nettoNetto = −netto del reso).

    Fatturato = fatturato netto del venduto (spedito − resi nel periodo) − resi fuori periodo
"""

from __future__ import annotations

import pandas as pd


def _block(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"lordo": 0.0, "netto": 0.0, "nettoSped": 0.0, "nettoRes": 0.0,
                "paiaSped": 0.0, "paiaRes": 0.0, "paiaNet": 0.0, "ordini": 0}
    return {
        "lordo": float(df["lordoSpedito"].sum()),
        "netto": float(df["nettoNetto"].sum()),
        "nettoSped": float(df["nettoSpedito"].sum()),
        "nettoRes": float(df["nettoReso"].sum()),
        "paiaSped": float(df["paiaSpedite"].sum()),
        "paiaRes": float(df["paiaRese"].sum()),
        "paiaNet": float(df["paiaNette"].sum()),
        "ordini": int(df.loc[df["ordineId"] != "", "ordineId"].nunique()),
    }


def calculate_global_metrics_detailed(df: pd.DataFrame) -> dict:
    """Ritorna {tot, dir, est} con lordo/netto/nettoSped/nettoRes/paiaSped/paiaRes/paiaNet/ordini."""
    if df is None or df.empty:
        return {"tot": _block(df), "dir": _block(df), "est": _block(df)}
    est = df[df["tipoSpedizione"] == "ESTERNA"]
    dir_ = df[df["tipoSpedizione"] != "ESTERNA"]
    return {"tot": _block(df), "dir": _block(dir_), "est": _block(est)}


def kpi_reali(venduto: pd.DataFrame, resi_fp: pd.DataFrame | None) -> dict:
    """KPI di un sottoinsieme di dati: la definizione canonica di Fatturato e derivati.

    Denominatori dei % reso: paia spedite / netto spedito del solo venduto del periodo.
    """
    m = _block(venduto)
    r = _block(resi_fp)

    fatt_reale = m["netto"] + r["netto"]              # r["netto"] è negativo
    # le paia nette non possono essere negative: succede quando per quella fetta ci sono solo resi di
    # vendite fuori periodo (spedite 0, rese 17 ⇒ −17): si mostra 0
    paia_nette = max(0.0, m["paiaNet"] + r["paiaNet"])
    paia_rese = m["paiaRes"] + r["paiaRes"]
    resi_valore = m["nettoRes"] + r["nettoRes"]

    return {
        "fattReale": fatt_reale,
        "lordo": m["lordo"],
        "nettoSpedito": m["nettoSped"],
        "resiPeriodo": m["nettoRes"],                  # resi di vendite del periodo
        "resiFuoriPeriodo": r["nettoRes"],             # resi di vendite fuori periodo (valore positivo)
        "ordini": m["ordini"],
        # Scontrino Medio = fatturato netto spedito per ordine (valore di un ordine alla spedizione,
        # prima dei resi): rapporto, quindi coerente a qualunque livello di dettaglio
        "scontrinoMedio": m["nettoSped"] / m["ordini"] if m["ordini"] > 0 else 0.0,
        "paiaSped": m["paiaSped"],
        "paiaResePeriodo": m["paiaRes"],
        "paiaReseFuoriPeriodo": r["paiaRes"],
        "paiaRes": paia_rese,
        "paiaNette": paia_nette,
        "valMedio": fatt_reale / paia_nette if paia_nette > 0 else 0.0,
        "percReso": paia_rese / m["paiaSped"] if m["paiaSped"] > 0 else 0.0,
        "percResoValore": resi_valore / m["nettoSped"] if m["nettoSped"] > 0 else 0.0,
    }


def kpi_per_canale(venduto: pd.DataFrame, resi_fp: pd.DataFrame | None) -> dict:
    """{tot, dir, est} → kpi_reali per ciascun canale (DIRETTO / ESTERNA)."""
    def split(df, esterna: bool):
        if df is None or df.empty:
            return df
        mask = df["tipoSpedizione"] == "ESTERNA"
        return df[mask] if esterna else df[~mask]

    return {
        "tot": kpi_reali(venduto, resi_fp),
        "dir": kpi_reali(split(venduto, False), split(resi_fp, False)),
        "est": kpi_reali(split(venduto, True), split(resi_fp, True)),
    }


def compute_channel_kpi(df: pd.DataFrame, resi_fp_df: pd.DataFrame, predicate=None) -> dict:
    """KPI di un sottoinsieme (es. un marketplace) del venduto e dei resi fuori periodo."""
    if predicate is not None:
        df = df[predicate(df)]
        if resi_fp_df is not None and not resi_fp_df.empty:
            resi_fp_df = resi_fp_df[predicate(resi_fp_df)]
    return kpi_reali(df, resi_fp_df)
