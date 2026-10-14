"""Test suite per core/assistant_tools.py.

Verifica:
- HR Ferie & Sovrapposizioni (policy a voce, no ROL, controllo permessi RBAC)
- Agenda Condivisa Multi-Persona & Reparto
- Fast Analytics SQL (< 20ms)
- Tracking Spedizioni (GLS, DHL, UPS, BRT, Poste)
- Fast-Path Formatter
"""
from __future__ import annotations

import sqlite3
import pytest

from core import assistant_tools, ferie, roles, agenda


@pytest.fixture
def test_db():
    """In-memory SQLite DB con tabelle necessarie per i test."""
    conn = sqlite3.connect(":memory:")
    # Inizializza schemi
    agenda.init_agenda_tables(conn)
    roles.init_roles(conn)
    ferie.init_ferie_tables(conn)

    # Crea tabella righe per test analytics
    conn.execute("""
    CREATE TABLE righe (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_vendita TEXT,
        data_reso TEXT,
        mkp TEXT,
        sku13 TEXT,
        paia_spedite REAL,
        netto_spedito REAL,
        lordo_spedito REAL
    );
    """)

    # Popola dipendenti
    conn.execute("""
    INSERT INTO dipendenti (nome, email, totale_annuo, mattina_inizio, mattina_fine, pomeriggio_inizio, pomeriggio_fine, attivo, creato_il, aggiornato_il)
    VALUES 
    ('Marco Ripari', 'marco.ripari@falc.biz', 31.0, '08:00', '12:00', '14:00', '18:00', 1, '2026-01-01', '2026-01-01'),
    ('Giampiero Mattei', 'giampiero.mattei@falc.biz', 31.0, '08:00', '12:00', '14:00', '18:00', 1, '2026-01-01', '2026-01-01'),
    ('Luca Bianchi', 'luca.bianchi@falc.biz', 31.0, '08:00', '12:00', '14:00', '18:00', 1, '2026-01-01', '2026-01-01');
    """)

    # Crea ruolo Utente senza permessi ferie
    conn.execute("INSERT OR REPLACE INTO ruoli (nome, descrizione, is_system, creato_il) VALUES ('Utente', 'Utente base', 0, '2026-01-01');")
    conn.execute("INSERT OR REPLACE INTO permessi_ruolo (ruolo, pagina_id, attivo) VALUES ('Utente', '00_Home', 1);")

    # Ruoli
    conn.execute("""
    INSERT INTO utenti_ruoli (email, ruolo, assegnato_il)
    VALUES 
    ('marco.ripari@falc.biz', 'Admin', '2026-01-01'),
    ('giampiero.mattei@falc.biz', 'Logistica', '2026-01-01'),
    ('luca.bianchi@falc.biz', 'Utente', '2026-01-01');
    """)

    # Ferie esistenti per Giampiero il 2026-10-20
    conn.execute("""
    INSERT INTO ferie_assenze (nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note, creato_il)
    VALUES ('Giampiero Mattei', '2026-10-20', '2026-10-22', 'Ferie', 3.0, 'Ferie concordate', '', '2026-01-01');
    """)

    # Dati vendita di test
    conn.execute("""
    INSERT INTO righe (data_vendita, data_reso, mkp, sku13, paia_spedite, netto_spedito, lordo_spedito)
    VALUES 
    ('2026-09-10', NULL, 'Zalando', 'SKU1234567890', 2.0, 150.0, 183.0),
    ('2026-09-15', '2026-09-20', 'Zalando', 'SKU1234567890', 1.0, 75.0, 91.5),
    ('2026-09-18', NULL, 'Amazon', 'SKU9876543210', 3.0, 240.0, 292.8);
    """)

    conn.commit()
    return conn


def test_ferie_verifica_sovrapposizioni(test_db):
    """Verifica il corretto rilevamento di colleghi assenti con policy a voce."""
    # Periodo con sovrapposizione su Giampiero
    res = assistant_tools.ferie_verifica_sovrapposizioni(
        test_db, "marco.ripari@falc.biz", data_inizio="2026-10-21", data_fine="2026-10-21"
    )
    assert res["success"] is True
    assert res["sovrapposizione"] is True
    assert res["totale_colleghi_assenti"] == 1
    assert res["dettaglio_assenze"][0]["nome"] == "Giampiero Mattei"
    assert "concordati a voce" in res["policy_promemoria"].lower()

    # Periodo libero
    res_libero = assistant_tools.ferie_verifica_sovrapposizioni(
        test_db, "marco.ripari@falc.biz", data_inizio="2026-11-01", data_fine="2026-11-05"
    )
    assert res_libero["success"] is True
    assert res_libero["sovrapposizione"] is False
    assert res_libero["totale_colleghi_assenti"] == 0

    # Filtro reparto Logistica
    res_rep = assistant_tools.ferie_verifica_sovrapposizioni(
        test_db, "marco.ripari@falc.biz", data_inizio="2026-10-20", reparto="Logistica"
    )
    assert res_rep["sovrapposizione"] is True
    assert res_rep["dettaglio_assenze"][0]["nome"] == "Giampiero Mattei"


def test_ferie_consulta_saldo(test_db):
    """Verifica il calcolo del saldo ferie e nota su assenza di ROL separati."""
    res = assistant_tools.ferie_consulta_saldo(test_db, "giampiero.mattei@falc.biz")
    assert res["success"] is True
    assert res["totale_annuo_spettante"] == 31.0
    assert res["giorni_goduti"] == 3.0
    assert res["giorni_residui"] == 28.0
    assert "ROL" in res["nota_rol"]


def test_ferie_registra_assenza_rbac(test_db):
    """Verifica che solo gli Admin o utenti autorizzati possano registrare ferie."""
    # Utente non admin prova a registrare: DEVE ESSERE NEGATO
    res_negato = assistant_tools.ferie_registra_assenza(
        test_db,
        user_email="luca.bianchi@falc.biz",  # Ruolo Logistica
        dipendente="Giampiero Mattei",
        data_inizio="2026-12-01",
        data_fine="2026-12-01",
    )
    assert res_negato["success"] is False
    assert res_negato.get("permesso_negato") is True

    # Admin prova a registrare: AUTORIZZATO
    res_ok = assistant_tools.ferie_registra_assenza(
        test_db,
        user_email="marco.ripari@falc.biz",  # Ruolo Admin
        dipendente="Giampiero Mattei",
        data_inizio="2026-12-01",
        data_fine="2026-12-01",
        durata_giorni=1.0,
    )
    assert res_ok["success"] is True
    assert res_ok["dipendente"] == "Giampiero Mattei"


def test_agenda_trova_slot_condiviso(test_db):
    """Verifica il calcolo degli slot orari comuni tra persona e reparto."""
    # 2026-10-20: Giampiero è in ferie
    res_ferie = assistant_tools.agenda_trova_slot_condiviso(
        test_db,
        user_email="marco.ripari@falc.biz",
        data="2026-10-20",
        persona="Giampiero Mattei",
    )
    assert res_ferie["success"] is True
    assert "Giampiero Mattei" in res_ferie["assenti_ferie"]

    # 2026-10-15: giorno normale senza ferie né impegni
    res_libero = assistant_tools.agenda_trova_slot_condiviso(
        test_db,
        user_email="marco.ripari@falc.biz",
        data="2026-10-15",
        persona="Giampiero Mattei",
        durata_minuti_richiesta=60,
    )
    assert res_libero["success"] is True
    assert len(res_libero["slot_liberi"]) > 0
    # Verifica che gli slot rispettino mattina o pomeriggio
    for s in res_libero["slot_liberi"]:
        assert s["durata_minuti"] >= 60


def test_analytics_kpi_rapido(test_db):
    """Verifica le query veloci su vendite, resi e canali."""
    # Panoramica
    res_pano = assistant_tools.analytics_kpi_rapido(
        test_db, metrica="panoramica", periodo_inizio="2026-09-01", periodo_fine="2026-09-30"
    )
    assert res_pano["success"] is True
    assert res_pano["fatturato_netto"] == 465.0  # 150 + 75 + 240
    assert res_pano["paia_spedite"] == 6  # 2 + 1 + 3
    assert res_pano["num_resi"] == 1

    # Top Canali
    res_can = assistant_tools.analytics_kpi_rapido(
        test_db, metrica="top_canali", periodo_inizio="2026-09-01", periodo_fine="2026-09-30"
    )
    assert res_can["success"] is True
    assert len(res_can["canali"]) == 2


def test_tracking_spedizione():
    """Verifica riconoscimento vettore e deeplink ufficiale."""
    # GLS
    t_gls = assistant_tools.tracking_spedizione("AX000012849IT")
    assert t_gls["success"] is True
    assert "GLS" in t_gls["vettore"]
    assert "gls-italy.com" in t_gls["url_diretto"]

    # DHL
    t_dhl = assistant_tools.tracking_spedizione("1234567890", vettore="DHL")
    assert t_dhl["success"] is True
    assert "DHL" in t_dhl["vettore"]
    assert "dhl.com" in t_dhl["url_diretto"]

    # UPS
    t_ups = assistant_tools.tracking_spedizione("1Z9999999999999999")
    assert t_ups["success"] is True
    assert "UPS" in t_ups["vettore"]
    assert "ups.com" in t_ups["url_diretto"]


def test_prompt_requires_tools():
    """Verifica rilevamento corretto dei prompt che necessitano dei tool."""
    assert assistant_tools.prompt_requires_tools("Trova un buco domani con la logistica") is True
    assert assistant_tools.prompt_requires_tools("Quante ferie mi restano?") is True
    assert assistant_tools.prompt_requires_tools("Traccia questo pacco GLS: AX000012849IT") is True
    assert assistant_tools.prompt_requires_tools("Quanto abbiamo fatturato ieri?") is True
    assert assistant_tools.prompt_requires_tools("Ciao!") is False


def test_fast_path_formatter():
    """Verifica la formattazione deterministica Markdown ultra-rapida."""
    # Ferie overlap
    out_ass = {
        "success": True,
        "intervallo": {"da": "2026-10-20", "a": "2026-10-22"},
        "reparto_richiesto": "Logistica",
        "persona_richiesta": "Tutte",
        "sovrapposizione": True,
        "totale_colleghi_assenti": 1,
        "dettaglio_assenze": [{"nome": "Giampiero Mattei", "ruolo": "Logistica", "tipo": "Ferie", "data_inizio": "2026-10-20", "data_fine": "2026-10-22", "giorni": 3.0}],
    }
    md = assistant_tools.format_fast_path_response("ferie_verifica_sovrapposizioni", {}, out_ass)
    assert md is not None
    assert "Giampiero Mattei" in md
    assert "concordate a voce" in md

    # Tracking
    out_trk = {
        "success": True,
        "codice": "AX000012849IT",
        "vettore": "GLS Italy",
        "icona": "🚚",
        "url_diretto": "https://www.gls-italy.com/it/servizi-per-destinatari/ricerca-spedizione/?match=AX000012849IT",
        "istruzioni": "Segui il collo",
    }
    md_trk = assistant_tools.format_fast_path_response("tracking_spedizione", {}, out_trk)
    assert md_trk is not None
    assert "GLS Italy" in md_trk
    assert "AX000012849IT" in md_trk


def test_agenda_visualizza_impegni_fast_path_formatter():
    """Verifica la formattazione pulita degli impegni in agenda senza convenevoli."""
    out_empty = {"success": True, "eventi": []}
    md_empty = assistant_tools.format_fast_path_response("agenda_visualizza_impegni", {"data_da": "2026-10-15"}, out_empty)
    assert "Nessun impegno in programma" in md_empty

    out_events = {
        "success": True,
        "eventi": [
            {
                "titolo": "Caricamento catalogo",
                "data_inizio": "2026-10-15 14:00",
                "data_fine": "2026-10-15 15:30",
                "luogo": "Meet",
                "note": "Con Giampiero",
            }
        ],
    }
    md_ev = assistant_tools.format_fast_path_response("agenda_visualizza_impegni", {"data_da": "2026-10-15"}, out_events)
    assert "Caricamento catalogo" in md_ev
    assert "14:00 - 15:30" in md_ev
    assert "Con Giampiero" in md_ev


def test_detect_direct_fast_path_comprehensive(test_db):
    """Verifica che tutte le tipologie di richieste operative standard vengano intercettate sub-10ms."""
    email = "marco.ripari@falc.biz"

    # 1. Tracking
    assert assistant_tools.detect_direct_fast_path("Traccia questo pacco GLS: AX000012849IT") is not None
    assert assistant_tools.detect_direct_fast_path("Traccia questo pacco UPS: 1Z46W1446843904912") is not None

    # 2. Ferie saldo
    res_saldo = assistant_tools.detect_direct_fast_path("Quanti giorni di ferie mi restano quest'anno?", conn=test_db, user_email=email)
    assert res_saldo is not None
    assert "Saldo Ferie" in res_saldo

    # 3. Ferie sovrapposizioni
    res_sov = assistant_tools.detect_direct_fast_path("C'è qualcuno in ferie tra il 20 e il 25 Ottobre?", conn=test_db, user_email=email)
    assert res_sov is not None
    assert "Giampiero Mattei" in res_sov

    # 4. Agenda visualizza
    agenda.crea_evento(test_db, email, "Riunione test", "2026-10-15 10:00", "2026-10-15 11:00", note="Con Giampiero")
    res_ag1 = assistant_tools.detect_direct_fast_path("Cosa ho in programma per oggi?", conn=test_db, user_email=email)
    assert res_ag1 is not None

    res_ag2 = assistant_tools.detect_direct_fast_path("Domani quali impegni ho insieme a Giampiero?", conn=test_db, user_email=email)
    assert res_ag2 is not None
    assert "Riunione test" in res_ag2

    # 5. Slot condiviso
    res_slot = assistant_tools.detect_direct_fast_path("Trova uno slot libero domani insieme a Giampiero Mattei.", conn=test_db, user_email=email)
    assert res_slot is not None
    assert "Slot Disponibili" in res_slot

    # 6. Analytics con mese e con periodo esplicito (prompt 207)
    res_kpi = assistant_tools.detect_direct_fast_path("Quanto abbiamo fatturato a Settembre 2026?", conn=test_db, user_email=email)
    assert res_kpi is not None
    assert "Dati di Vendita" in res_kpi

    res_kpi2 = assistant_tools.detect_direct_fast_path(
        "Dimmi fatturato, paia spedite, paia rese, paia nette e % reso del periodo 01/09/2026 al 30/09/2026",
        conn=test_db,
        user_email=email,
    )
    assert res_kpi2 is not None
    assert "Paia Spedite" in res_kpi2
    assert "Paia Rese" in res_kpi2
    assert "Paia Nette" in res_kpi2


def test_tracking_rich_status_and_milestones():
    """Verifica che il tracking restituisca lo stato attuale del pacco, tappe e consegna prevista."""
    res_gls = assistant_tools.tracking_spedizione("AX000012849IT")
    assert res_gls["success"] is True
    assert "In Transito" in res_gls["stato"]
    assert "consegna_prevista" in res_gls
    assert len(res_gls["tappe"]) >= 4
    assert res_gls["tappe"][0]["completato"] is True

    md = assistant_tools.format_fast_path_response("tracking_spedizione", {}, res_gls)
    assert "Stato Spedizione GLS Italy" in md
    assert "Stato Attuale" in md
    assert "Avanzamento Spedizione" in md
    assert "Civitanova Marche" in md


def test_get_scoped_tools_schema_with_intent():
    """Verifica che get_scoped_tools_schema isoli i tool pertinenti o None per chat."""
    assert assistant_tools.get_scoped_tools_schema("", intent="chat") is None
    assert assistant_tools.get_scoped_tools_schema("", intent="agenda") == assistant_tools.AGENDA_TOOLS_SCHEMA
    assert assistant_tools.get_scoped_tools_schema("", intent="ferie") == assistant_tools.HR_TOOLS_SCHEMA
    assert assistant_tools.get_scoped_tools_schema("", intent="analytics") == assistant_tools.ANALYTICS_TOOLS_SCHEMA
    assert assistant_tools.get_scoped_tools_schema("", intent="tracking") == assistant_tools.TRACKING_TOOLS_SCHEMA


