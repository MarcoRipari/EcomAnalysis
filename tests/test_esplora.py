"""Esplora per dimensioni: una tabella filtrabile con gli stessi numeri del resto dell'app."""
import datetime as dt

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from core import esplora, metrics, pipeline
from tests.conftest import carica, riga

PERIODO = (dt.date(2026, 1, 1), dt.date(2026, 1, 31))
PREC = (dt.date(2025, 1, 1), dt.date(2025, 1, 31))
ZAL = dict(mkp="Zalando", naz="DE")


@pytest.fixture
def pipe(conn):
    carica(conn,
           dataset=[riga("A1", "10/01/2026"), riga("A2", "11/01/2026", **ZAL),
                    riga("A3", "12/01/2026", sku="ZZZZZZZ111111-37", **ZAL),
                    riga("B1", "28/12/2025", mkp="Amazon", naz="FR"),
                    riga("C1", "10/01/2025", **ZAL)],
           resi=[riga("A2", "11/01/2026", data_reso="20/01/2026", stato="Reso", **ZAL),
                 riga("B1", "28/12/2025", data_reso="03/01/2026", stato="Reso", mkp="Amazon", naz="FR")])
    return pipeline.build_pipeline_from_db(conn, PERIODO, PREC)


def dati(p):
    return (p.current_data, p.resi_fp_current), (p.old_data, p.resi_fp_old)


def test_la_somma_delle_righe_e_il_fatturato_dei_dati_filtrati(pipe):
    cur, old = dati(pipe)
    for raggruppa in (["Brand", "Collezione"], ["Marketplace", "Nazione"], ["Nazione"], []):
        t = esplora.tabella(cur, old, {}, raggruppa, "2026", "2025")
        assert t["Fatturato 2026"].sum() == pytest.approx(metrics.kpi_reali(*cur)["fattReale"])
        assert t["Fatturato 2025"].sum() == pytest.approx(metrics.kpi_reali(*old)["fattReale"])


def test_filtri_marketplace_nazione(pipe):
    cur, old = dati(pipe)
    filtri = {"mkp": ["Zalando"], "nazione": ["DE"]}
    t = esplora.tabella(cur, old, filtri, ["Marketplace", "Nazione"], "2026", "2025")
    assert list(t["Marketplace"]) == ["Zalando"] and list(t["Nazione"]) == ["DE"]
    atteso = metrics.kpi_reali(esplora.filtra(cur[0], filtri), esplora.filtra(cur[1], filtri))["fattReale"]
    assert t["Fatturato 2026"].iloc[0] == pytest.approx(atteso)
    assert t["Fatturato 2025"].iloc[0] == pytest.approx(100.0)      # C1 dell'anno precedente


def test_il_reso_fuori_periodo_compare_nel_suo_marketplace(pipe):
    cur, old = dati(pipe)
    t = esplora.tabella(cur, old, {}, ["Marketplace"], "2026", "2025").set_index("Marketplace")
    assert t.loc["Amazon", "Fatturato 2026"] == pytest.approx(-100.0)
    assert t.loc["Amazon", "Paia Nette 2026"] == 0                   # mai negative


def test_opzioni_a_cascata(pipe):
    cur, old = dati(pipe)
    frames = [*cur, *old]
    assert esplora.opzioni(frames, "mkp", {}) == ["Amazon", "Naturino", "Zalando"]
    assert esplora.opzioni(frames, "nazione", {"mkp": ["Zalando"]}) == ["DE"]
    assert esplora.opzioni(frames, "nazione", {"mkp": ["Amazon", "Naturino"]}) == ["FR", "IT"]


def test_senza_confronto_e_senza_dimensioni(conn):
    carica(conn, dataset=[riga("A1", "10/01/2026")])
    p = pipeline.build_pipeline_from_db(conn, PERIODO, None)
    t = esplora.tabella((p.current_data, p.resi_fp_current), None, {}, [], "2026", "2025")
    assert len(t) == 1 and "Fatturato 2025" not in t.columns
    assert t["Fatturato 2026"].iloc[0] == pytest.approx(100.0)
    vuota = esplora.tabella((p.current_data, p.resi_fp_current), None, {"mkp": ["Nessuno"]}, ["Brand"], "2026", "2025")
    assert vuota.empty
