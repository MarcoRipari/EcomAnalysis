"""Fixture condivise: DB SQLite temporaneo e costruttore di righe CSV grezze (layout posizionale)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import db, engine  # noqa: E402

NESSUNA_DATA = "01/01/0001"


def riga(ordine, data, data_reso=NESSUNA_DATA, stato="Spedito", importo="121,00", qta="1",
         sku="ABCDEFG123456-35", mkp="Naturino", naz="IT", acquirente="MARIO", riga_id="1"):
    """Una riga grezza a 16 colonne (stesso layout di CONFIG.COLS_DATASET). 121 € lordi = 100 € netti."""
    return [mkp, naz, "NATURINO CLASSIC", "", data, data_reso, stato, acquirente, ordine, riga_id,
            "EUR", importo, importo, qta, "", sku]


def to_processed(righe: list[list[str]]) -> pd.DataFrame:
    raw = pd.DataFrame(righe, dtype=str)
    return engine.process_dataset(raw, {})


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    yield c
    c.close()


def carica(conn, dataset=(), resi=()):
    if dataset:
        db.upsert_dataset(conn, to_processed(list(dataset)), "dataset.csv")
    if resi:
        db.upsert_resi(conn, to_processed(list(resi)), "resi.csv")
