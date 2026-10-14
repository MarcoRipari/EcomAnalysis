import datetime as dt
import pytest

from core import db, topbar
from tests.conftest import carica, riga

PERIODO = (dt.date(2026, 1, 1), dt.date(2026, 3, 31))


def test_canali_esterni_dinamici_e_perimetri(conn):
    # Setup dati:
    # A1: Diretto (Naturino)
    # A2: Zalando con ordine contenente _ZFS (tipo_spedizione ESTERNA)
    # A3: Amazon con ordine contenente _FBA (tipo_spedizione ESTERNA)
    carica(
        conn,
        dataset=[
            riga("ORD001", "10/01/2026", mkp="Naturino"),
            riga("ORD002_ZFS", "15/01/2026", mkp="Zalando"),
            riga("ORD003_FBA", "20/01/2026", mkp="Amazon"),
            riga("ORD004_ZFS", "10/05/2026", mkp="Zalando"),  # fuori periodo
        ],
    )

    # 1. Rilevamento canali attivi nel periodo [2026-01-01, 2026-03-31]
    canali = db.canali_esterni_attivi(conn, PERIODO[0], PERIODO[1])
    nomi_canali = [c[0] for c in canali]
    assert "Zalando ZFS" in nomi_canali
    assert "Amazon FBA" in nomi_canali

    # 2. Topbar get_perimetri
    perimetri = topbar.get_perimetri(conn, PERIODO[0], PERIODO[1])
    assert "Totale" in perimetri
    assert "Canali Diretti" in perimetri
    assert "Zalando ZFS" in perimetri
    assert "Amazon FBA" in perimetri

    # 3. Query periodo con perimetro Canali Diretti ("2")
    venduto_dir, _ = db.query_period(conn, PERIODO[0], PERIODO[1], perimetro="2")
    assert len(venduto_dir) == 1
    assert venduto_dir.iloc[0]["ordineId"] == "ORD001"

    # 4. Query periodo con perimetro Zalando ZFS ("ZFS")
    venduto_zfs, _ = db.query_period(conn, PERIODO[0], PERIODO[1], perimetro="ZFS")
    assert len(venduto_zfs) == 1
    assert venduto_zfs.iloc[0]["ordineId"] == "ORD002_ZFS"

    # 5. Query periodo con perimetro Amazon FBA ("FBA")
    venduto_fba, _ = db.query_period(conn, PERIODO[0], PERIODO[1], perimetro="FBA")
    assert len(venduto_fba) == 1
    assert venduto_fba.iloc[0]["ordineId"] == "ORD003_FBA"


def test_canali_esterni_vuoti_se_solo_diretti(conn):
    carica(
        conn,
        dataset=[
            riga("ORD001", "10/01/2026", mkp="Naturino"),
            riga("ORD002", "15/01/2026", mkp="Falcotto"),
        ],
    )
    canali = db.canali_esterni_attivi(conn, PERIODO[0], PERIODO[1])
    assert canali == []

    perimetri = topbar.get_perimetri(conn, PERIODO[0], PERIODO[1])
    assert list(perimetri.keys()) == ["Totale", "Canali Diretti"]
