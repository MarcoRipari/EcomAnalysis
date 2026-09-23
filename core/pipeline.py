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

from dataclasses import dataclass, field

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
) -> Pipeline:
    anagrafica = engine.load_anagrafica(anagrafica_file)

    current_data = engine.process_dataset(engine.read_raw_csv(dataset_current_file), anagrafica)
    old_data = (engine.process_dataset(engine.read_raw_csv(dataset_old_file), anagrafica)
                if dataset_old_file is not None else current_data.iloc[0:0].copy())

    periodo_current = metrics.get_period_bounds(current_data)
    periodo_old = metrics.get_period_bounds(old_data) if not old_data.empty else (None, None)
    metrics.apply_period_bound_to_returns(current_data, *periodo_current)
    if not old_data.empty:
        metrics.apply_period_bound_to_returns(old_data, *periodo_old)

    diag_pre_filtro = metrics.conta_per_canale(current_data)

    resi_raw_current = engine.process_dataset(engine.read_raw_csv(resi_current_file), anagrafica)
    resi_raw_old = (engine.process_dataset(engine.read_raw_csv(resi_old_file), anagrafica)
                    if (resi_old_file is not None and not old_data.empty) else current_data.iloc[0:0].copy())

    current_data = _filtra_perimetro(current_data, perimetro)
    old_data = _filtra_perimetro(old_data, perimetro)
    resi_raw_current = _filtra_perimetro(resi_raw_current, perimetro)
    resi_raw_old = _filtra_perimetro(resi_raw_old, perimetro)

    metriche_grezze_current = metrics.calculate_global_metrics_detailed(current_data)
    metriche_grezze_old = metrics.calculate_global_metrics_detailed(old_data) if not old_data.empty else None

    esito_resi_current = reconciler.reconcile_resi_con_dataset(
        current_data, resi_raw_current, *periodo_current)
    esito_resi_old = (
        reconciler.reconcile_resi_con_dataset(old_data, resi_raw_old, *periodo_old)
        if not old_data.empty else {"convertiti": [], "duplicati": [], "standalone": pd.DataFrame(), "fuoriPeriodo": []}
    )

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
