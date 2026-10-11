"""Regole di periodo dei resi e Fatturato (definizione unica, vedi core/metrics.py)."""
import datetime as dt

import pytest

from core import db, metrics
from tests.conftest import carica, riga

GEN = (dt.date(2026, 1, 1), dt.date(2026, 1, 31))


def _fatt_reale(conn, periodo=GEN):
    venduto, resi_fp = db.query_period(conn, *periodo)
    return metrics.compute_channel_kpi(venduto, resi_fp)["fattReale"], venduto, resi_fp


def test_vendita_gennaio_reso_febbraio_resta_spedito(conn):
    carica(conn,
           dataset=[riga("A1", "10/01/2026")],
           resi=[riga("A1", "10/01/2026", data_reso="05/02/2026", stato="Reso")])
    fatt, venduto, resi_fp = _fatt_reale(conn)
    assert fatt == pytest.approx(100.0)
    assert venduto["paiaRese"].sum() == 0 and venduto["paiaNette"].sum() == 1
    assert resi_fp.empty


def test_vendita_dicembre_reso_gennaio_e_reso_fuori_periodo(conn):
    carica(conn,
           dataset=[riga("B1", "28/12/2025")],
           resi=[riga("B1", "28/12/2025", data_reso="03/01/2026", stato="Reso")])
    fatt, venduto, resi_fp = _fatt_reale(conn)
    assert venduto.empty
    assert len(resi_fp) == 1
    assert fatt == pytest.approx(-100.0)


def test_vendita_e_reso_nello_stesso_periodo_si_annullano(conn):
    carica(conn,
           dataset=[riga("D1", "05/01/2026")],
           resi=[riga("D1", "05/01/2026", data_reso="20/01/2026", stato="Reso")])
    fatt, venduto, resi_fp = _fatt_reale(conn)
    assert fatt == pytest.approx(0.0)
    assert venduto["paiaRese"].sum() == 1
    assert resi_fp.empty


def test_reso_senza_ordine_nel_db_riduce_il_fatturato(conn):
    """Ordine mai caricato nel DATASET: il reso esiste comunque e va sottratto."""
    carica(conn, resi=[riga("C1", "20/12/2025", data_reso="15/01/2026", stato="Reso")])
    fatt, venduto, resi_fp = _fatt_reale(conn)
    assert venduto.empty and len(resi_fp) == 1
    assert fatt == pytest.approx(-100.0)


def test_reso_senza_ordine_con_data_vendita_nel_periodo_e_un_ordine_reale(conn):
    """Il reso porta con sé la data di vendita: +100 (vendita) −100 (reso) nello stesso periodo."""
    carica(conn, resi=[riga("C2", "10/01/2026", data_reso="15/01/2026", stato="Reso")])
    fatt, venduto, resi_fp = _fatt_reale(conn)
    assert len(venduto) == 1 and resi_fp.empty
    assert venduto["paiaSpedite"].sum() == 1 and venduto["paiaRese"].sum() == 1
    assert fatt == pytest.approx(0.0)


def test_ordine_caricato_dopo_il_suo_reso_non_si_conta_due_volte(conn):
    resi = [riga("C2", "10/01/2026", data_reso="15/01/2026", stato="Reso")]
    dataset = [riga("C2", "10/01/2026")]
    carica(conn, resi=resi)
    carica(conn, dataset=dataset)
    carica(conn, dataset=dataset)               # ricarico idempotente
    carica(conn, resi=resi)
    assert conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0] == 1
    fatt, venduto, resi_fp = _fatt_reale(conn)
    assert fatt == pytest.approx(0.0) and resi_fp.empty and venduto["paiaRese"].sum() == 1


def test_somma_dei_casi(conn):
    carica(conn,
           dataset=[riga("A1", "10/01/2026"), riga("B1", "28/12/2025"), riga("D1", "05/01/2026")],
           resi=[riga("A1", "10/01/2026", data_reso="05/02/2026", stato="Reso"),
                 riga("B1", "28/12/2025", data_reso="03/01/2026", stato="Reso"),
                 riga("D1", "05/01/2026", data_reso="20/01/2026", stato="Reso"),
                 riga("C1", "20/12/2025", data_reso="15/01/2026", stato="Reso")])
    fatt, _, _ = _fatt_reale(conn)
    assert fatt == pytest.approx(100.0 + 0.0 - 100.0 - 100.0)  # A1 + D1 − B1 − C1


def test_ricarico_resi_idempotente(conn):
    resi = [riga("B1", "28/12/2025", data_reso="03/01/2026", stato="Reso")]
    carica(conn, dataset=[riga("B1", "28/12/2025")], resi=resi)
    prima = _fatt_reale(conn)[0]
    carica(conn, resi=resi)
    assert _fatt_reale(conn)[0] == pytest.approx(prima)


def test_scenario_cinque_ordini_gennaio(conn):
    """Importi lordi (IVA inclusa): fatturato = (200 + 0 − 100 + 0 + (20 − 20)) / 1,21."""
    carica(conn,
           dataset=[riga("O1", "02/01/2026", importo="200,00"),
                    riga("O2", "02/01/2026", importo="50,00"),
                    riga("O3", "28/12/2025", importo="100,00"),
                    riga("O4", "02/02/2026", importo="100,00")],
           resi=[riga("O2", "02/01/2026", data_reso="05/01/2026", stato="Reso", importo="50,00"),
                 riga("O3", "28/12/2025", data_reso="03/01/2026", stato="Reso", importo="100,00"),
                 riga("O5", "10/01/2026", data_reso="15/01/2026", stato="Reso", importo="20,00")])
    fatt, _, _ = _fatt_reale(conn)
    assert fatt * 1.21 == pytest.approx(100.0)
