"""
Metriche globali, KPI e gestione del periodo di riferimento.
Porting di: calculateGlobalMetricsDetailed, computeChannelKPI, contaPerCanale,
getPeriodBounds, isDateInPeriod, applyPeriodBoundToReturns (helpers.gs).
"""

from __future__ import annotations

import pandas as pd


def get_period_bounds(df: pd.DataFrame):
    """min/max di dataVendita tra le righe con data valida. -> (start, end) Timestamp o None."""
    valid = df["dataVendita"].dropna()
    if valid.empty:
        return None, None
    return valid.min(), valid.max()


def is_date_in_period(date, period_start, period_end) -> bool:
    """Vero se `date` è dentro [start, end]. Se data mancante o periodo non determinabile -> True
    (stesso comportamento "permissivo" dell'originale)."""
    if pd.isna(date):
        return True
    if period_start is None or period_end is None:
        return True
    return period_start <= date <= period_end


def apply_period_bound_to_returns(df: pd.DataFrame, period_start, period_end) -> pd.DataFrame:
    """
    Normalizza i resi nativi (isReso=True) rispetto al periodo: se dataReso cade FUORI dal
    periodo, la riga torna Spedito puro. Muta e ritorna il DataFrame (in-place sulle colonne).
    Va chiamata SUBITO dopo process_dataset e PRIMA di ogni altro calcolo.
    """
    if period_start is None or period_end is None:
        return df

    in_period = df["dataReso"].apply(lambda d: is_date_in_period(d, period_start, period_end))
    revert_mask = df["isReso"] & (~in_period)

    df.loc[revert_mask, "isReso"] = False
    df.loc[revert_mask, "paiaRese"] = 0.0
    df.loc[revert_mask, "paiaNette"] = df.loc[revert_mask, "paiaSpedite"]
    df.loc[revert_mask, "nettoReso"] = 0.0
    df.loc[revert_mask, "nettoNetto"] = df.loc[revert_mask, "nettoSpedito"]
    df.loc[revert_mask, "lordoReso"] = 0.0
    df.loc[revert_mask, "lordoNetto"] = df.loc[revert_mask, "lordoSpedito"]
    return df


def conta_per_canale(df: pd.DataFrame) -> dict:
    """Diagnostica rapida righe/ordini per canale DIRETTO vs ESTERNA."""
    if df.empty:
        return {"righeDiretti": 0, "righeEsterni": 0, "ordiniDiretti": 0, "ordiniEsterni": 0}
    est = df[df["tipoSpedizione"] == "ESTERNA"]
    dir_ = df[df["tipoSpedizione"] != "ESTERNA"]
    return {
        "righeDiretti": len(dir_), "righeEsterni": len(est),
        "ordiniDiretti": dir_.loc[dir_["ordineId"] != "", "ordineId"].nunique(),
        "ordiniEsterni": est.loc[est["ordineId"] != "", "ordineId"].nunique(),
    }


def _block(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"lordo": 0.0, "netto": 0.0, "paiaSped": 0.0, "paiaRes": 0.0, "paiaNet": 0.0, "ordini": 0}
    return {
        "lordo": float(df["lordoSpedito"].sum()),
        "netto": float(df["nettoNetto"].sum()),
        "paiaSped": float(df["paiaSpedite"].sum()),
        "paiaRes": float(df["paiaRese"].sum()),
        "paiaNet": float(df["paiaNette"].sum()),
        "ordini": int(df.loc[df["ordineId"] != "", "ordineId"].nunique()),
    }


def calculate_global_metrics_detailed(df: pd.DataFrame) -> dict:
    """Ritorna {tot, dir, est} con lordo/netto/paiaSped/paiaRes/paiaNet/ordini."""
    if df.empty:
        empty = _block(df)
        return {"tot": empty, "dir": empty.copy(), "est": empty.copy()}
    est = df[df["tipoSpedizione"] == "ESTERNA"]
    dir_ = df[df["tipoSpedizione"] != "ESTERNA"]
    return {"tot": _block(df), "dir": _block(dir_), "est": _block(est)}


def compute_channel_kpi(df: pd.DataFrame, standalone_df: pd.DataFrame, predicate=None) -> dict:
    """
    KPI di sintesi (Fatturato Netto Reale, Ordini, Paia Nette, Valore Medio Paio, % Reso)
    per un sottoinsieme di dati. `standalone_df` sono i rimborsi extra (esitoResi.standalone),
    sempre sommati al netto per ottenere il fatturato realmente rettificato.
    """
    filtered = df[predicate(df)] if predicate is not None else df
    filtered_standalone = standalone_df[predicate(standalone_df)] if (predicate is not None and not standalone_df.empty) else standalone_df

    m = calculate_global_metrics_detailed(filtered)["tot"]
    m_resi = calculate_global_metrics_detailed(filtered_standalone)["tot"] if not filtered_standalone.empty else _block(filtered_standalone)

    fatt_reale = m["netto"] + m_resi["netto"]
    val_medio = fatt_reale / m["paiaNet"] if m["paiaNet"] > 0 else 0.0
    perc_reso = m["paiaRes"] / m["paiaSped"] if m["paiaSped"] > 0 else 0.0

    return {"fattReale": fatt_reale, "ordini": m["ordini"], "paiaNette": m["paiaNet"],
            "valMedio": val_medio, "percReso": perc_reso}
