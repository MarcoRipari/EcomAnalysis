"""Smoke test: ogni pagina di report si apre senza eccezioni su dati sintetici (Streamlit AppTest)."""
import datetime as dt
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from core import db, pipeline  # noqa: E402
from tests.conftest import carica, riga  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGINE = [
    "00_Home", "00_Carica_Dati", "11_Log_Riconciliazione", "01_Dashboard", "02_Y2Y_Generale",
    "03_Articoli_e_Collezioni", "04_Canali_Marketplace", "05_Nazioni", "06_Analisi_Resi",
    "07_Trova_SKU", "08_Taglie", "09_Sell_Through", "10_Export_Dati", "13_Correzioni_DB",
    "14_Configurazioni", "15_Anagrafica", "16_Gestione_Ruoli", "17_Nuovo_Utente",
    "18_Stato_Connessioni",
    "20_Catalogo_Panoramica", "21_Catalogo_Articoli", "22_Foto_Archivio", "23_Foto_Caricamento",
    "24_Ferie_Calendario", "25_Ferie_Registra", "26_Ferie_Riepilogo", "27_Ferie_Configurazioni",
    "99_Test_Chatbot"
]

PERIODO_A = (dt.date(2026, 1, 1), dt.date(2026, 3, 31))
PERIODO_B = (dt.date(2025, 1, 1), dt.date(2025, 3, 31))


@pytest.fixture(params=["con_resi", "senza_resi_fuori_periodo"])
def ambiente(request, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ROOT))
    conn = db.connect()                                   # data/ecombi.db nella cartella temporanea
    carica(conn,
           dataset=[riga("A1", "10/01/2026"), riga("A2", "12/02/2026", naz="DE", mkp="Zalando", sku="ABCDEFG123999-36"),
                    riga("B1", "28/12/2025"), riga("C1", "05/02/2025", sku="ZZZZZZZ111111-37"),
                    riga("C2", "20/02/2025", mkp="Zalando_ZFS", naz="FR")],
           resi=[riga("A1", "10/01/2026", data_reso="20/01/2026", stato="Reso")]
           + ([riga("B1", "28/12/2025", data_reso="03/01/2026", stato="Reso"),
               riga("X9", "15/12/2025", data_reso="05/02/2026", stato="Reso", naz="FR")]
              if request.param == "con_resi" else []))
    pipe = pipeline.build_pipeline_from_db(conn, PERIODO_A, PERIODO_B, "1", {})
    return {"pipeline": pipe, "sel_periodo_a": PERIODO_A, "sel_periodo_b": PERIODO_B,
            "periodo_a_label": "2026-01-01 → 2026-03-31", "periodo_b_label": "2025-01-01 → 2025-03-31",
            "sel_confronta_2anni": False, "perimetro_label": "TOTALE", "user_role": "Admin"}


@pytest.mark.parametrize("pagina", PAGINE)
def test_pagina_si_apre_senza_errori(pagina, ambiente):
    at = AppTest.from_file(str(ROOT / "pages" / f"{pagina}.py"), default_timeout=60)
    for k, v in ambiente.items():
        at.session_state[k] = v
    if pagina == "07_Trova_SKU":
        at.run()
        at.text_input[0].set_value("ABCDEFG").run()
    else:
        at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_correzioni_anteprima_e_applica(ambiente):
    at = AppTest.from_file(str(ROOT / "pages" / "13_Correzioni_DB.py"), default_timeout=60)
    for k, v in ambiente.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception
    at.selectbox[0].select("nazione")
    at.text_input[0].set_value("FR")
    at.text_input[1].set_value("XX")
    at.button[0].click().run()               # Anteprima
    assert not at.exception, [e.value for e in at.exception]
    assert any("righe verrebbero modificate" in str(m.value) for m in at.success)


def _topbar_app():
    from core import topbar
    topbar.render()


def test_barra_periodo_genera_i_dati_al_primo_avvio(ambiente):
    at = AppTest.from_function(_topbar_app, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    pipe = at.session_state["pipeline"]
    assert len(pipe.current_data) > 0
    assert at.session_state["sel_periodo_a"][1] == dt.date(2026, 2, 12)       # ultima vendita presente nel DB


def test_barra_periodo_applica_un_nuovo_periodo(ambiente):
    at = AppTest.from_function(_topbar_app, default_timeout=60)
    at.run()
    at.date_input[0].set_value((dt.date(2026, 1, 1), dt.date(2026, 1, 31)))
    at.checkbox[0].check()
    at.button[0].click().run()                                              # Applica
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["sel_periodo_a"] == (dt.date(2026, 1, 1), dt.date(2026, 1, 31))
    assert at.session_state["sel_confronta_2anni"] is True


def test_barra_periodo_con_db_vuoto(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ROOT))
    at = AppTest.from_function(_topbar_app, default_timeout=60)
    at.run()
    assert not at.exception and "pipeline" not in at.session_state
    assert any("DB è vuoto" in str(i.value) for i in at.info)
