"""Trova SKU: prefissi 7/9/13, periodo vs intero DB, quadratura delle tabelle col totale."""
import datetime as dt

import pytest

from core import sku_search as sk
from tests.conftest import carica, riga

A = "ABCDEFG123456-35"      # codice ABCDEFG, SKU13 ABCDEFG123456, taglia 35
B = "ABCDEFG123999-36"      # stesso codice (7), SKU13 diverso
C = "ZZZZZZZ111111-35"      # altro codice


@pytest.fixture
def db_sku(conn):
    carica(conn,
           dataset=[riga("O1", "10/01/2026", sku=A), riga("O2", "15/01/2026", sku=B, naz="DE"),
                    riga("O3", "12/01/2026", sku=C), riga("O4", "20/03/2025", sku=A, mkp="Zalando"),
                    riga("O5", "28/12/2025", sku=A)],
           resi=[riga("O1", "10/01/2026", data_reso="18/01/2026", stato="Reso", sku=A),
                 riga("O5", "28/12/2025", data_reso="03/01/2026", stato="Reso", sku=A)])
    return conn


GEN = (dt.date(2026, 1, 1), dt.date(2026, 1, 31))


@pytest.mark.parametrize("prefisso,n_sku", [("ABCDEFG", 2), ("ABCDEFG12", 2), ("ABCDEFG123456", 1),
                                              ("abcdefg-12", 2), ("ZZZ", 1), ("QQQ", 0)])
def test_prefissi_7_9_13(db_sku, prefisso, n_sku):
    venduto, resi_fp = sk.cerca(db_sku, prefisso, sk.FULL_DB_PERIOD)
    trovati = sk.articoli_trovati(venduto, resi_fp, {})
    assert len(trovati) == n_sku


def test_periodo_selezionato_vs_intero_db(db_sku):
    v_per, r_per = sk.cerca(db_sku, "ABCDEFG123456", GEN)
    v_all, r_all = sk.cerca(db_sku, "ABCDEFG123456", sk.FULL_DB_PERIOD)
    # gennaio 2026: O1 (venduto e reso nello stesso mese → 0) e il reso fuori periodo di O5 (−100)
    assert sk.kpi(v_per, r_per)["fattReale"] == pytest.approx(-100.0)
    # intero DB: O1 (0) + O4 (100) + O5 (venduto 100, reso 100 → 0)
    assert sk.kpi(v_all, r_all)["fattReale"] == pytest.approx(100.0)
    assert len(r_all) == 0   # con periodo illimitato nessun reso è "fuori periodo"


@pytest.mark.parametrize("dimensione", ["Marketplace", "Nazione", "Taglia", "Canale", "SKU", "Mese"])
def test_ogni_tabella_somma_al_totale(db_sku, dimensione):
    for periodo in (GEN, sk.FULL_DB_PERIOD):
        venduto, resi_fp = sk.cerca(db_sku, "ABCDEFG", periodo)
        totale = sk.kpi(venduto, resi_fp)["fattReale"]
        t = sk.tabella_per(venduto, resi_fp, dimensione)
        assert t["Fatturato"].sum() == pytest.approx(totale)
        assert t["Share %"].sum() == pytest.approx(1.0) if totale != 0 else True


def test_taglie_ordinate_e_dettaglio_righe(db_sku):
    venduto, resi_fp = sk.cerca(db_sku, "ABCDEFG", sk.FULL_DB_PERIOD)
    assert list(sk.per_taglia(venduto, resi_fp)["Taglia"]) == ["35", "36"]
    det = sk.dettaglio_righe(venduto, resi_fp)
    assert det["Fatturato"].sum() == pytest.approx(sk.kpi(venduto, resi_fp)["fattReale"])
