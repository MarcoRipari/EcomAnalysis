"""Test per la gestione dell'anagrafica nel DB: parsing, upsert con sostituzione, deduzione genere e integrazione nel core."""
import pytest
from core import db, engine, pipeline
from tests.conftest import carica, riga


def test_parse_anagrafica_reale():
    records = engine.parse_anagrafica("anagrafica_261.csv", fonte_file="anagrafica_261.csv")
    assert len(records) == 4131
    # Verifica presenza campi chiave
    r0 = records[0]
    assert r0["sku7"] == "0502415"
    assert r0["fondo_cod"] == "01"
    assert r0["colore_cod"] == "0C03"
    assert r0["sku13"] == "0502415010C03"
    assert r0["descrizione"] == "NATURINO SKYLINE"
    assert r0["brand"] == "NATURINO LIMANGO"
    assert r0["genere"] == "BAMBINO"
    assert r0["fonte_file"] == "anagrafica_261.csv"


def test_deduce_genere():
    assert engine.deduce_genere("NATURINO", "COCOON") == "BAMBINO"
    assert engine.deduce_genere("FALCOTTO", "F8 CREPE") == "BAMBINO"
    assert engine.deduce_genere("VOILE BLANCHE", "VOILE BLANCHE UOMO") == "UOMO"
    assert engine.deduce_genere("VOILE BLANCHE", "VOILE BLANCHE DONNA") == "DONNA"
    assert engine.deduce_genere("Candice Cooper", "Candice Cooper D") == "DONNA"
    assert engine.deduce_genere("Candice Cooper", "Candice Cooper U") == "UOMO"
    assert engine.deduce_genere("W6YZ Adulto", "W6YZ UOMO SPORT") == "UOMO"
    assert engine.deduce_genere("W6YZ Bimbo", "W6YZ CALZATURE BIMBO SPORT") == "BAMBINO"
    assert engine.deduce_genere("FLOWER MOUNTAIN", "FLOWER MOUNTAIN UNISEX") == "UNISEX"
    assert engine.deduce_genere("VOILE BLANCHE ACCESSORI", "VOILE BLANCHE ACCESSORI") == "ACCESSORI"
    assert engine.deduce_genere("FM ACCESSORI", "FLOWER M.ADULT.ABBIGL.") == "ABBIGLIAMENTO"


def test_upsert_anagrafica_con_sostituzione(conn):
    rec_base = {
        "sku13": "2018797171B91",
        "sku7": "2018797",
        "brand_cod": "060",
        "brand": "VOILE BLANCHE",
        "linea_cod": "00",
        "linea": "VOILE BLANCHE UOMO",
        "reparto_cod": "6",
        "tipo_cod": "C",
        "categoria": "001",
        "descrizione": "PARIS POWER MAN.",
        "fondo_cod": "17",
        "fondo_desc": "SUEDE/NYLON",
        "colore_cod": "1B91",
        "colore_desc": "SILKY GREY-WHITE-LEAD",
        "taglia_base": "42",
        "valore": "6,0",
        "data_disponibilita": "02/05/2025",
        "flag": "",
        "stagione": "2026",
        "semestre": "1",
        "genere": "UOMO",
        "fonte_file": "anagrafica_261.csv",
        "aggiornato_il": "2026-01-01T10:00:00",
    }

    # 1. Primo caricamento: 1 riga nuova
    res1 = db.upsert_anagrafica(conn, [rec_base], fonte_file="anagrafica_261.csv")
    assert res1["righe_nuove"] == 1
    assert res1["righe_aggiornate"] == 0
    assert res1["totale_articoli"] == 1

    # 2. Secondo caricamento con dati aggiornati per lo stesso sku13: deve SOSTITUIRE
    rec_aggiornato = dict(rec_base)
    rec_aggiornato["descrizione"] = "PARIS POWER MAN NUOVO"
    rec_aggiornato["semestre"] = "2"
    rec_aggiornato["fonte_file"] = "anagrafica_262.csv"
    rec_aggiornato["aggiornato_il"] = "2026-02-01T10:00:00"

    rec_secondo = {
        "sku13": "0502415010C03",
        "sku7": "0502415",
        "brand_cod": "014",
        "brand": "NATURINO",
        "linea_cod": "00",
        "linea": "NATURINO SKYLINE",
        "reparto_cod": "6",
        "tipo_cod": "C",
        "categoria": "001",
        "descrizione": "NATURINO SKYLINE",
        "fondo_cod": "01",
        "fondo_desc": "NAPPA SPAZZ.",
        "colore_cod": "0C03",
        "colore_desc": "AZURE",
        "taglia_base": "20",
        "valore": "0,0",
        "data_disponibilita": "09/09/2025",
        "flag": "",
        "stagione": "2026",
        "semestre": "2",
        "genere": "BAMBINO",
        "fonte_file": "anagrafica_262.csv",
        "aggiornato_il": "2026-02-01T10:00:00",
    }

    res2 = db.upsert_anagrafica(conn, [rec_aggiornato, rec_secondo], fonte_file="anagrafica_262.csv")
    assert res2["righe_nuove"] == 1
    assert res2["righe_aggiornate"] == 1
    assert res2["totale_articoli"] == 2

    # Verifica che il record sostituito contenga effettivamente i valori del file 262
    cur = conn.cursor()
    row = cur.execute("SELECT descrizione, semestre, fonte_file FROM anagrafica WHERE sku13='2018797171B91'").fetchone()
    assert row[0] == "PARIS POWER MAN NUOVO"
    assert row[1] == "2"
    assert row[2] == "anagrafica_262.csv"


def test_get_anagrafica_dict(conn):
    rec = {
        "sku13": "2018797171B91",
        "sku7": "2018797",
        "brand_cod": "060",
        "brand": "VOILE BLANCHE",
        "linea_cod": "00",
        "linea": "VOILE BLANCHE UOMO",
        "reparto_cod": "6",
        "tipo_cod": "C",
        "categoria": "001",
        "descrizione": "PARIS POWER MAN.",
        "fondo_cod": "17",
        "fondo_desc": "SUEDE/NYLON",
        "colore_cod": "1B91",
        "colore_desc": "SILKY GREY-WHITE-LEAD",
        "taglia_base": "42",
        "valore": "6,0",
        "data_disponibilita": "02/05/2025",
        "flag": "",
        "stagione": "2026",
        "semestre": "1",
        "genere": "UOMO",
        "fonte_file": "261",
        "aggiornato_il": "2026-01-01",
    }
    db.upsert_anagrafica(conn, [rec], "test")
    anag = db.get_anagrafica_dict(conn)

    # Indicizzazione per SKU13
    assert "2018797171B91" in anag
    item_sku13 = anag["2018797171B91"]
    assert item_sku13["desc"] == "PARIS POWER MAN."
    assert item_sku13["clz"] == "VOILE BLANCHE"
    assert item_sku13["genere"] == "UOMO"

    # Indicizzazione per SKU7 (codice articolo)
    assert "2018797" in anag
    item_sku7 = anag["2018797"]
    assert item_sku7["desc"] == "PARIS POWER MAN."
    assert item_sku7["genere"] == "UOMO"


def test_sincronizza_genere_righe(conn):
    # Carica righe nel DB con genere inizialmente 'NON CLASSIFICATO'
    carica(conn, dataset=[
        riga("O1", "10/01/2026", sku="2018797-17-1B91-42"),
        riga("O2", "11/01/2026", sku="0502415-01-0C03-20"),
        riga("O3", "12/01/2026", sku="9999999-00-0000-30"),  # non in anagrafica
    ])

    # Popola anagrafica
    recs = [
        {
            "sku13": "2018797171B91", "sku7": "2018797", "brand_cod": "060", "brand": "VOILE BLANCHE",
            "linea_cod": "", "linea": "VOILE BLANCHE UOMO", "reparto_cod": "", "tipo_cod": "",
            "categoria": "", "descrizione": "PARIS POWER", "fondo_cod": "17", "fondo_desc": "",
            "colore_cod": "1B91", "colore_desc": "", "taglia_base": "42", "valore": "",
            "data_disponibilita": "", "flag": "", "stagione": "2026", "semestre": "1",
            "genere": "UOMO", "fonte_file": "261", "aggiornato_il": "2026-01-01",
        },
        {
            "sku13": "0502415010C03", "sku7": "0502415", "brand_cod": "014", "brand": "NATURINO",
            "linea_cod": "", "linea": "NATURINO SKYLINE", "reparto_cod": "", "tipo_cod": "",
            "categoria": "", "descrizione": "SKYLINE", "fondo_cod": "01", "fondo_desc": "",
            "colore_cod": "0C03", "colore_desc": "", "taglia_base": "20", "valore": "",
            "data_disponibilita": "", "flag": "", "stagione": "2026", "semestre": "1",
            "genere": "BAMBINO", "fonte_file": "261", "aggiornato_il": "2026-01-01",
        },
    ]
    db.upsert_anagrafica(conn, recs, "test")

    # Sincronizza
    n = db.sincronizza_genere_righe(conn)
    assert n == 2

    # Verifica i generi in righe
    cur = conn.cursor()
    g1 = cur.execute("SELECT genere FROM righe WHERE sku13='2018797171B91'").fetchone()[0]
    g2 = cur.execute("SELECT genere FROM righe WHERE sku13='0502415010C03'").fetchone()[0]
    g3 = cur.execute("SELECT genere FROM righe WHERE sku13='9999999000000'").fetchone()[0]
    assert g1 == "UOMO"
    assert g2 == "BAMBINO"
    assert g3 == "NON CLASSIFICATO"


def test_pipeline_carica_anagrafica_da_db(conn):
    rec = {
        "sku13": "2018797171B91", "sku7": "2018797", "brand_cod": "060", "brand": "VOILE BLANCHE",
        "linea_cod": "", "linea": "VOILE BLANCHE UOMO", "reparto_cod": "", "tipo_cod": "",
        "categoria": "", "descrizione": "PARIS POWER MAN.", "fondo_cod": "17", "fondo_desc": "",
        "colore_cod": "1B91", "colore_desc": "", "taglia_base": "42", "valore": "",
        "data_disponibilita": "", "flag": "", "stagione": "2026", "semestre": "1",
        "genere": "UOMO", "fonte_file": "261", "aggiornato_il": "2026-01-01",
    }
    db.upsert_anagrafica(conn, [rec], "test")
    carica(conn, dataset=[riga("O1", "10/01/2026", sku="2018797-17-1B91-42")])

    import datetime as dt
    pipe = pipeline.build_pipeline_from_db(
        conn,
        (dt.date(2026, 1, 1), dt.date(2026, 1, 31)),
        None,
        "1",
        anagrafica=None,  # deve recuperarlo automaticamente dal DB
    )

    assert "2018797171B91" in pipe.anagrafica
    assert pipe.anagrafica["2018797171B91"]["desc"] == "PARIS POWER MAN."


def test_svuota_anagrafica(conn):
    rec = {
        "sku13": "2018797171B91", "sku7": "2018797", "brand_cod": "060", "brand": "VOILE BLANCHE",
        "linea_cod": "", "linea": "VOILE BLANCHE UOMO", "reparto_cod": "", "tipo_cod": "",
        "categoria": "", "descrizione": "PARIS POWER MAN.", "fondo_cod": "17", "fondo_desc": "",
        "colore_cod": "1B91", "colore_desc": "", "taglia_base": "42", "valore": "",
        "data_disponibilita": "", "flag": "", "stagione": "2026", "semestre": "1",
        "genere": "UOMO", "fonte_file": "261", "aggiornato_il": "2026-01-01",
    }
    db.upsert_anagrafica(conn, [rec], "test")
    assert conn.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0] == 1

    # Svuota solo anagrafica
    db.svuota_anagrafica(conn)
    assert conn.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0] == 0
    assert db.get_anagrafica_dict(conn) == {}

