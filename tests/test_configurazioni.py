import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest

from core import config as CFG
from core import settings
from core.topbar import anno_fiscale


def test_default_settings_validi_e_non_vuoti():
    defs = settings.get_default_settings()
    assert isinstance(defs, dict)
    assert defs["anno_fiscale"]["mese_inizio"] == 11
    assert defs["iva"]["default"] == 0.21
    assert defs["iva"]["aliquote"]["IT"] == 0.21
    assert defs["tassi_cambio"]["EUR"] == 1.00
    assert "USD" in defs["tassi_cambio"]
    assert "GBP" in defs["tassi_cambio"]


def test_salvataggio_e_caricamento_json(tmp_path):
    p_json = tmp_path / "config_test.json"
    p_db = tmp_path / "test.db"

    custom = {
        "anno_fiscale": {"mese_inizio": 1},
        "iva": {
            "default": 0.22,
            "aliquote": {"IT": 0.22, "FR": 0.20, "DE": 0.19},
        },
        "tassi_cambio": {
            "EUR": 1.00,
            "USD": 1.10,
            "GBP": 0.85,
        },
    }

    saved = settings.save_settings(custom, path=p_json, db_path=p_db)
    assert saved["anno_fiscale"]["mese_inizio"] == 1
    assert saved["iva"]["default"] == 0.22
    assert saved["iva"]["aliquote"]["DE"] == 0.19
    assert saved["tassi_cambio"]["USD"] == 1.10

    # Verifica persistenza su file JSON
    assert p_json.exists()
    with open(p_json, "r", encoding="utf-8") as f:
        loaded_raw = json.load(f)
    assert loaded_raw["anno_fiscale"]["mese_inizio"] == 1

    # Ricarica con load_settings
    loaded = settings.load_settings(path=p_json, db_path=p_db)
    assert loaded["anno_fiscale"]["mese_inizio"] == 1
    assert loaded["iva"]["aliquote"]["DE"] == 0.19
    assert loaded["tassi_cambio"]["GBP"] == 0.85

    # Ripristina i default di runtime
    settings.reset_to_defaults()


def test_resilienza_file_mancante_o_corrotto(tmp_path):
    p_json = tmp_path / "non_esiste.json"
    p_db = tmp_path / "non_esiste.db"

    # Se non esiste, ricrea i default
    res = settings.load_settings(path=p_json, db_path=p_db)
    assert res["anno_fiscale"]["mese_inizio"] == 11
    assert p_json.exists(), "Il file JSON deve essere stato ricreato automaticamente"

    # Se corrotto con contenuto invalido
    with open(p_json, "w", encoding="utf-8") as f:
        f.write("{ invalid json content :::")

    res_corrotto = settings.load_settings(path=p_json, db_path=p_db)
    assert res_corrotto["anno_fiscale"]["mese_inizio"] == 11
    assert res_corrotto["iva"]["default"] == 0.21

    # Ripristina runtime
    settings.reset_to_defaults()


def test_ridondanza_bidirezionale_sqlite(tmp_path):
    p_json = tmp_path / "config.json"
    p_db = tmp_path / "test.db"

    custom = {
        "anno_fiscale": {"mese_inizio": 7},
        "iva": {
            "default": 0.20,
            "aliquote": {"IT": 0.22, "ES": 0.21},
        },
        "tassi_cambio": {"EUR": 1.00, "USD": 1.08},
    }

    # Salva su entrambi
    settings.save_settings(custom, path=p_json, db_path=p_db)

    # 1. Elimina il file JSON: il caricamento deve ripristinarlo dal DB SQLite
    p_json.unlink()
    assert not p_json.exists()

    recuperato_da_db = settings.load_settings(path=p_json, db_path=p_db)
    assert recuperato_da_db["anno_fiscale"]["mese_inizio"] == 7
    assert recuperato_da_db["iva"]["aliquote"]["ES"] == 0.21
    assert p_json.exists(), "Il file JSON deve essere stato rigenerato a partire dal DB SQLite"

    # 2. Elimina il DB SQLite: il caricamento deve ripristinarlo dal file JSON
    p_db.unlink()
    assert not p_db.exists()

    recuperato_da_json = settings.load_settings(path=p_json, db_path=p_db)
    assert recuperato_da_json["anno_fiscale"]["mese_inizio"] == 7

    # Ripristina runtime
    settings.reset_to_defaults()


def test_modifica_anno_fiscale_dinamica():
    # Imposta mese inizio ad Aprile (4)
    settings.save_settings({
        "anno_fiscale": {"mese_inizio": 4},
        "iva": {"default": 0.21, "aliquote": {"IT": 0.21}},
        "tassi_cambio": {"EUR": 1.00},
    })

    assert CFG.MESE_INIZIO_ANNO_FISCALE == 4
    # Con mese inizio = 4, anno fiscale contenente il 15/05/2026 va dal 01/04/2026 al 31/03/2027
    ini, fine = anno_fiscale(dt.date(2026, 5, 15))
    assert ini == dt.date(2026, 4, 1)
    assert fine == dt.date(2027, 3, 31)

    # Ripristina a Novembre (11)
    settings.reset_to_defaults()
    assert CFG.MESE_INIZIO_ANNO_FISCALE == 11
    ini_def, fine_def = anno_fiscale(dt.date(2026, 5, 15))
    assert ini_def == dt.date(2025, 11, 1)
    assert fine_def == dt.date(2026, 10, 31)
