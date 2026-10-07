"""
Orchestrazione della pipeline dati — porting della parte "preparazione dati" di
showUnifiedGenerator() / showSellThroughGenerator() in menu.gs:
1. process_dataset su DATASET (+ DATASET OLD se presente)
2. calcolo periodo di riferimento + applyPeriodBoundToReturns
3. process_dataset su RESI (+ RESI OLD)
4. filtro perimetro logistico (Totale / Diretti / Esterni) su tutti e 4
5. metriche grezze PRIMA della riconciliazione
6. riconciliazione RESI -> DATASET (muta in-place)

Il risultato è un oggetto Pipeline con tutto il necessario per alimentare le pagine
Streamlit dei singoli report (equivalenti ai moduli generateXxxModulo di reports.gs).
"""

from __future__ import annotations

import gc
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from . import engine, metrics, reconciler


@dataclass
class Pipeline:
    perimetro: str  # '1' Totale, '2' Diretti, '3' Esterni
    current_data: pd.DataFrame
    old_data: pd.DataFrame
    anagrafica: dict
    metriche_grezze_current: dict
    metriche_grezze_old: dict | None
    esito_resi_current: dict
    esito_resi_old: dict
    diag_pre_filtro: dict
    diag_post_filtro: dict = field(default_factory=dict)


def _filtra_perimetro(df: pd.DataFrame, perimetro: str) -> pd.DataFrame:
    if df.empty or perimetro == "1":
        return df
    tipo = "DIRETTO" if perimetro == "2" else "ESTERNA"
    return df[df["tipoSpedizione"] == tipo].reset_index(drop=True)


def run_pipeline(
    dataset_current_file,
    resi_current_file,
    dataset_old_file=None,
    resi_old_file=None,
    anagrafica_file=None,
    perimetro: str = "1",
    col_sito_nazione: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> Pipeline:
    """Modalità "a file" (legacy): rielabora da zero i CSV/TXT ad ogni generazione. Tenuta per
    compatibilità/uso occasionale — per l'uso quotidiano vedi build_pipeline_from_db(), che
    legge dal DB incrementale e non richiede più ricaricare i file ad ogni report."""
    def step(label):
        if progress:
            progress(label)

    anagrafica = engine.load_anagrafica(anagrafica_file)

    def _load(f):
        raw = engine.read_raw_csv(f)
        if col_sito_nazione is not None:
            engine.apply_nazione_correction_inplace(raw, col_sito_nazione)
        processed = engine.process_dataset(raw, anagrafica)
        del raw
        return processed

    step("Lettura e normalizzazione DATASET…")
    current_data = _load(dataset_current_file)
    step("Lettura e normalizzazione DATASET OLD…")
    old_data = _load(dataset_old_file) if dataset_old_file is not None else current_data.iloc[0:0].copy()
    gc.collect()

    periodo_current = metrics.get_period_bounds(current_data)
    periodo_old = metrics.get_period_bounds(old_data) if not old_data.empty else (None, None)
    metrics.apply_period_bound_to_returns(current_data, *periodo_current)
    if not old_data.empty:
        metrics.apply_period_bound_to_returns(old_data, *periodo_old)

    diag_pre_filtro = metrics.conta_per_canale(current_data)

    step("Lettura e normalizzazione RESI…")
    resi_raw_current = _load(resi_current_file)
    step("Lettura e normalizzazione RESI OLD…")
    resi_raw_old = (_load(resi_old_file)
                    if (resi_old_file is not None and not old_data.empty) else current_data.iloc[0:0].copy())
    gc.collect()

    current_data = _filtra_perimetro(current_data, perimetro)
    old_data = _filtra_perimetro(old_data, perimetro)
    resi_raw_current = _filtra_perimetro(resi_raw_current, perimetro)
    resi_raw_old = _filtra_perimetro(resi_raw_old, perimetro)

    metriche_grezze_current = metrics.calculate_global_metrics_detailed(current_data)
    metriche_grezze_old = metrics.calculate_global_metrics_detailed(old_data) if not old_data.empty else None

    step("Riconciliazione RESI (anno corrente)…")
    esito_resi_current = reconciler.reconcile_resi_con_dataset(
        current_data, resi_raw_current, *periodo_current)
    del resi_raw_current
    step("Riconciliazione RESI (anno precedente)…")
    esito_resi_old = (
        reconciler.reconcile_resi_con_dataset(old_data, resi_raw_old, *periodo_old)
        if not old_data.empty else {"convertiti": [], "duplicati": [], "standalone": pd.DataFrame(), "fuoriPeriodo": []}
    )
    del resi_raw_old
    gc.collect()

    diag_post_filtro = metrics.conta_per_canale(current_data)

    return Pipeline(
        perimetro=perimetro,
        current_data=current_data,
        old_data=old_data,
        anagrafica=anagrafica,
        metriche_grezze_current=metriche_grezze_current,
        metriche_grezze_old=metriche_grezze_old,
        esito_resi_current=esito_resi_current,
        esito_resi_old=esito_resi_old,
        diag_pre_filtro=diag_pre_filtro,
        diag_post_filtro=diag_post_filtro,
    )


# --------------------------------------------------------------------------------------
# Modalità DB (incrementale) — sostituisce run_pipeline() nell'uso quotidiano: nessun file
# da ricaricare, i dati arrivano da core/db.py per range di date già riconciliati riga per
# riga. Il resto della UI (le 9 pagine report) NON cambia: legge lo stesso oggetto Pipeline.
# --------------------------------------------------------------------------------------

def build_pipeline_from_db(conn, periodo_current: tuple, periodo_old: tuple | None,
                            perimetro: str = "1", anagrafica: dict | None = None) -> Pipeline:
    """
    `periodo_current` / `periodo_old` = (start, end) come date/Timestamp/stringa 'YYYY-MM-DD'.
    `periodo_old` può essere None se non serve un confronto Y2Y.
    """
    from . import db as dbmod

    anagrafica = anagrafica or {}

    current_data, standalone_current = dbmod.query_period(conn, *periodo_current, perimetro)
    if periodo_old is not None:
        old_data, standalone_old = dbmod.query_period(conn, *periodo_old, perimetro)
    else:
        old_data, standalone_old = current_data.iloc[0:0].copy(), current_data.iloc[0:0].copy()

    def _grezze(df):
        if df.empty:
            return metrics.calculate_global_metrics_detailed(df)
        tmp = df.copy()
        tmp["nettoNetto"] = tmp["nettoSpedito"]  # "prima della riconciliazione" = come se non ci
        return metrics.calculate_global_metrics_detailed(tmp)  # fossero stati sottratti i resi

    metriche_grezze_current = _grezze(current_data)
    metriche_grezze_old = _grezze(old_data) if not old_data.empty else None

    diag_pre_filtro = metrics.conta_per_canale(current_data)  # in modalità DB pre==post: il
    diag_post_filtro = diag_pre_filtro                          # perimetro è già applicato in query

    esito_resi_current = {"convertiti": [], "duplicati": [], "standalone": standalone_current, "fuoriPeriodo": []}
    esito_resi_old = {"convertiti": [], "duplicati": [], "standalone": standalone_old, "fuoriPeriodo": []}

    return Pipeline(
        perimetro=perimetro, current_data=current_data, old_data=old_data, anagrafica=anagrafica,
        metriche_grezze_current=metriche_grezze_current, metriche_grezze_old=metriche_grezze_old,
        esito_resi_current=esito_resi_current, esito_resi_old=esito_resi_old,
        diag_pre_filtro=diag_pre_filtro, diag_post_filtro=diag_post_filtro,
    )
