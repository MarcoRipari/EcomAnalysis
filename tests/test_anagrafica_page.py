import sqlite3
import pytest
from core import db, engine

@pytest.fixture
def conn(tmp_path):
    db_file = tmp_path / "test_anag.db"
    c = db.connect(str(db_file))
    return c


def test_regole_anagrafica_crud(conn):
    # Inizialmente vuote
    assert db.get_regole_anagrafica(conn) == []
    assert db.get_esclusioni_anagrafica(conn) == {"marchi": set(), "categorie": set()}

    # Inserimento regola marchio
    id1 = db.salva_regola_anagrafica(conn, "escludi_marchio", "FENDI", attivo=1, note="Licenza esclusa")
    # Inserimento regola categoria
    id2 = db.salva_regola_anagrafica(conn, "escludi_categoria", "003", attivo=1, note="Tomaie e semilavorati")

    regole = db.get_regole_anagrafica(conn)
    assert len(regole) == 2
    escl = db.get_esclusioni_anagrafica(conn)
    assert "FENDI" in escl["marchi"]
    assert "003" in escl["categorie"]

    # Disattiva regola marchio
    db.attiva_disattiva_regola_anagrafica(conn, id1, False)
    escl_after = db.get_esclusioni_anagrafica(conn)
    assert "FENDI" not in escl_after["marchi"]
    assert "003" in escl_after["categorie"]

    # Elimina regola categoria
    db.elimina_regola_anagrafica(conn, id2)
    assert len(db.get_regole_anagrafica(conn)) == 1


def test_modifica_stagione_anagrafica(conn):
    records = [
        {
            "sku13": "0503354010000", "sku7": "0503354", "brand": "FENDI", "linea": "JMR",
            "categoria": "001", "descrizione": "SANDALO", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "2026", "semestre": "1", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
        {
            "sku13": "0503354020000", "sku7": "0503354", "brand": "FENDI", "linea": "JMR",
            "categoria": "001", "descrizione": "SANDALO", "fondo_cod": "02", "colore_cod": "0000",
            "stagione": "2026", "semestre": "1", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
    ]
    db.upsert_anagrafica(conn, records, "f1.csv")

    # 1. Modifica solo singolo SKU13 in formato anno/stagione (2026/2)
    n1 = db.aggiorna_stagione_anagrafica(conn, "0503354010000", "2026/2", aggiorna_sku7=False)
    assert n1 == 1

    item1 = db.get_dettaglio_sku_anagrafica(conn, "0503354010000")
    item2 = db.get_dettaglio_sku_anagrafica(conn, "0503354020000")
    assert item1["stagione"] == "2026"
    assert item1["semestre"] == "2"
    assert item1["stagione_completa"] == "2026/2"
    assert item2["stagione"] == "2026"
    assert item2["semestre"] == "1"
    assert item2["stagione_completa"] == "2026/1"

    # 2. Modifica per tutto lo SKU7 in formato anno/stagione (2027/1)
    n2 = db.aggiorna_stagione_anagrafica(conn, "0503354", "2027/1", aggiorna_sku7=True)
    assert n2 == 2
    item1_after = db.get_dettaglio_sku_anagrafica(conn, "0503354010000")
    item2_after = db.get_dettaglio_sku_anagrafica(conn, "0503354020000")
    assert item1_after["stagione"] == "2027"
    assert item1_after["semestre"] == "1"
    assert item1_after["stagione_completa"] == "2027/1"
    assert item2_after["stagione"] == "2027"
    assert item2_after["semestre"] == "1"
    assert item2_after["stagione_completa"] == "2027/1"

    # 3. Modifica con valore senza slash (solo anno)
    db.aggiorna_stagione_anagrafica(conn, "0503354010000", "2028", aggiorna_sku7=False)
    item1_no_slash = db.get_dettaglio_sku_anagrafica(conn, "0503354010000")
    assert item1_no_slash["stagione"] == "2028"
    assert item1_no_slash["semestre"] == ""
    assert item1_no_slash["stagione_completa"] == "2028"

    # 4. Query stagioni frequenti complete
    q_sf = """
        SELECT CASE WHEN semestre IS NOT NULL AND semestre != '' THEN stagione || '/' || semestre ELSE stagione END AS stag_full
        FROM anagrafica
        WHERE stagione IS NOT NULL AND stagione != ''
        GROUP BY stag_full
        ORDER BY COUNT(*) DESC
    """
    stagioni_frequenti = [r[0] for r in conn.execute(q_sf).fetchall()]
    assert "2027/1" in stagioni_frequenti


def test_modifica_genere_e_ricalcolo(conn):
    records = [
        {
            "sku13": "SWKIDS0100000", "sku7": "SWKIDS0", "brand": "STUART WEITZMAN", "linea": "KIDS",
            "categoria": "001", "descrizione": "ADRIANNA.", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "NON CLASSIFICATO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
        {
            "sku13": "BALL010000000", "sku7": "BALL010", "brand": "BALLANTYNE", "linea": "BLE",
            "categoria": "001", "descrizione": "RUNNING BALLANTYNE DONNA BLE039", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "NON CLASSIFICATO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
    ]
    db.upsert_anagrafica(conn, records, "f1.csv")

    # Ricalcola generi con le euristiche avanzate
    res = db.ricalcola_tutti_generi(conn, solo_non_classificati=True)
    assert res["aggiornati"] == 2
    assert res["per_genere"].get("BAMBINO") == 1
    assert res["per_genere"].get("DONNA") == 1

    item_sw = db.get_dettaglio_sku_anagrafica(conn, "SWKIDS0100000")
    item_ball = db.get_dettaglio_sku_anagrafica(conn, "BALL010000000")
    assert item_sw["genere"] == "BAMBINO"
    assert item_ball["genere"] == "DONNA"

    # Modifica manuale singolo SKU
    db.aggiorna_genere_anagrafica(conn, "SWKIDS0100000", "DONNA")
    item_sw_manual = db.get_dettaglio_sku_anagrafica(conn, "SWKIDS0100000")
    assert item_sw_manual["genere"] == "DONNA"


def test_esclusioni_in_anagrafica_dict(conn):
    records = [
        {
            "sku13": "VOILE01000000", "sku7": "VOILE01", "brand": "VOILE BLANCHE", "linea": "DONNA",
            "categoria": "003", "descrizione": "TOMAIE ALICE", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "DONNA", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
        {
            "sku13": "NATUR01000000", "sku7": "NATUR01", "brand": "NATURINO", "linea": "COCOON",
            "categoria": "001", "descrizione": "PRIMI PASSI", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
    ]
    db.upsert_anagrafica(conn, records, "f1.csv")

    # Inizialmente non esclusi
    d1 = db.get_anagrafica_dict(conn)
    assert d1["VOILE01000000"]["escluso"] is False
    assert d1["NATUR01000000"]["escluso"] is False

    # Aggiungi regola di esclusione per categoria 003
    db.salva_regola_anagrafica(conn, "escludi_categoria", "003", attivo=1)

    d2 = db.get_anagrafica_dict(conn)
    assert d2["VOILE01000000"]["escluso"] is True
    assert d2["NATUR01000000"]["escluso"] is False


def test_upsert_anagrafica_rispetta_esclusioni(conn):
    # Imposta regole di esclusione
    db.salva_regola_anagrafica(conn, "escludi_marchio", "FENDI", attivo=1)
    db.salva_regola_anagrafica(conn, "escludi_categoria", "003", attivo=1)

    records = [
        {
            "sku13": "FENDI01000000", "sku7": "FENDI01", "brand": "FENDI", "linea": "JMR",
            "categoria": "001", "descrizione": "SANDALO FENDI", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
        {
            "sku13": "VOILE01000000", "sku7": "VOILE01", "brand": "VOILE BLANCHE", "linea": "DONNA",
            "categoria": "003", "descrizione": "TOMAIE ALICE", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "DONNA", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
        {
            "sku13": "NATUR01000000", "sku7": "NATUR01", "brand": "NATURINO", "linea": "COCOON",
            "categoria": "001", "descrizione": "PRIMI PASSI", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
    ]

    res = db.upsert_anagrafica(conn, records, "f1.csv")
    assert res["righe_nel_file"] == 3
    assert res["righe_escluse"] == 2
    assert res["righe_nuove"] == 1
    assert res["totale_articoli"] == 1

    # Verifica che nel DB ci sia solo NATURINO
    cur = conn.cursor()
    rows = cur.execute("SELECT sku13, brand FROM anagrafica").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "NATUR01000000"
    assert rows[0][1] == "NATURINO"


def test_elimina_e_conta_articoli_esclusi(conn):
    # Carica 3 articoli senza regole
    records = [
        {
            "sku13": "FENDI01000000", "sku7": "FENDI01", "brand": "FENDI", "linea": "JMR",
            "categoria": "001", "descrizione": "SANDALO FENDI", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
        {
            "sku13": "VOILE01000000", "sku7": "VOILE01", "brand": "VOILE BLANCHE", "linea": "DONNA",
            "categoria": "003", "descrizione": "TOMAIE ALICE", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "DONNA", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
        {
            "sku13": "NATUR01000000", "sku7": "NATUR01", "brand": "NATURINO", "linea": "COCOON",
            "categoria": "001", "descrizione": "PRIMI PASSI", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        },
    ]
    db.upsert_anagrafica(conn, records, "f1.csv")
    assert db.conta_articoli_esclusi_anagrafica(conn) == 0

    # Aggiungi regole di esclusione
    db.salva_regola_anagrafica(conn, "escludi_marchio", "FENDI", attivo=1)
    db.salva_regola_anagrafica(conn, "escludi_categoria", "003", attivo=1)

    assert db.conta_articoli_esclusi_anagrafica(conn) == 2

    # Elimina esclusi
    n_del = db.elimina_articoli_esclusi_anagrafica(conn)
    assert n_del == 2
    assert db.conta_articoli_esclusi_anagrafica(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0] == 1


def test_upsert_dataset_rispetta_esclusioni(conn):
    import pandas as pd
    # Popola anagrafica con 1 articolo categoria 003
    recs = [
        {
            "sku13": "SKU0030000000", "sku7": "SKU0030", "brand": "NATURINO",
            "categoria": "003", "descrizione": "TOMAIE", "fondo_cod": "01", "colore_cod": "0000",
            "stagione": "261", "genere": "BAMBINO", "fonte_file": "f1.csv", "aggiornato_il": "2026-01-01"
        }
    ]
    db.upsert_anagrafica(conn, recs, "f1.csv", applica_esclusioni=False)

    # Imposta regole
    db.salva_regola_anagrafica(conn, "escludi_marchio", "FENDI", attivo=1)
    db.salva_regola_anagrafica(conn, "escludi_categoria", "003", attivo=1)

    df_sales = pd.DataFrame({
        "ordineId": ["O1", "O2", "O3"],
        "rigaOrdine": ["1", "1", "1"],
        "skuFull": ["FENDI-01-42", "SKU003-01-20", "NATUR-01-22"],
        "sku13": ["FENDI01000000", "SKU0030000000", "NATUR01000000"],
        "sku7": ["FENDI01", "SKU0030", "NATUR01"],
        "taglia": ["42", "20", "22"],
        "mkp": ["ZALANDO", "ZALANDO", "ZALANDO"],
        "nazione": ["IT", "IT", "IT"],
        "clzOriginale": ["FENDI", "NATURINO", "NATURINO"],
        "clzMappata": ["FENDI", "NATURINO", "NATURINO"],
        "genere": ["DONNA", "BAMBINO", "BAMBINO"],
        "acquirente": ["ACQ1", "ACQ2", "ACQ3"],
        "dataVendita": [pd.Timestamp("2026-01-10"), pd.Timestamp("2026-01-10"), pd.Timestamp("2026-01-10")],
        "dataReso": [pd.NaT, pd.NaT, pd.NaT],
        "isReso": [False, False, False],
        "paiaSpedite": [1.0, 1.0, 1.0],
        "nettoSpedito": [100.0, 100.0, 100.0],
        "lordoSpedito": [121.0, 121.0, 121.0],
        "tipoSpedizione": ["DIRETTO", "DIRETTO", "DIRETTO"],
        "isPromo": [False, False, False],
    })

    stats = db.upsert_dataset(conn, df_sales, "sales.csv")
    assert stats["righe_nel_file"] == 3
    assert stats["righe_escluse"] == 2  # FENDI (marchio) e SKU003 (cat 003)
    assert stats["righe_nuove"] == 1

    # Solo NATUR01000000 deve essere presente in righe
    rows_db = conn.execute("SELECT sku13 FROM righe").fetchall()
    assert len(rows_db) == 1
    assert rows_db[0][0] == "NATUR01000000"
