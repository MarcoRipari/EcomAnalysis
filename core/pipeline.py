"""
Preparazione dati per le pagine: legge dal DB incrementale (core/db.py) il venduto e i resi
fuori periodo del periodo corrente e di quello di confronto. Nessuna lettura di file qui:
i CSV entrano solo dalla pagina Carica Dati / scripts/importa_db.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import db as dbmod


@dataclass
class Pipeline:
    perimetro: str  # '1' Totale, '2' Diretti, '3' Esterni
    current_data: pd.DataFrame
    old_data: pd.DataFrame
    resi_fp_current: pd.DataFrame   # resi fuori periodo, periodo corrente
    resi_fp_old: pd.DataFrame       # resi fuori periodo, periodo di confronto
    anagrafica: dict


def build_pipeline_from_db(conn, periodo_current: tuple, periodo_old: tuple | None,
                           perimetro: str = "1", anagrafica: dict | None = None) -> Pipeline:
    """`periodo_current` / `periodo_old` = (start, end) come date/Timestamp/stringa 'YYYY-MM-DD'.
    `periodo_old` può essere None se non serve un confronto Y2Y."""
    current_data, resi_fp_current = dbmod.query_period(conn, *periodo_current, perimetro)
    if periodo_old is not None:
        old_data, resi_fp_old = dbmod.query_period(conn, *periodo_old, perimetro)
    else:
        old_data, resi_fp_old = current_data.iloc[0:0].copy(), current_data.iloc[0:0].copy()

    return Pipeline(
        perimetro=perimetro, current_data=current_data, old_data=old_data,
        resi_fp_current=resi_fp_current, resi_fp_old=resi_fp_old, anagrafica=anagrafica or {},
    )
