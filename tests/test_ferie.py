from datetime import date, time
import sqlite3
import pandas as pd
import pytest

from core import ferie


@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    ferie.init_ferie_tables(conn)
    return conn


def test_init_ferie_tables(mem_conn):
    tables = [r[0] for r in mem_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "dipendenti" in tables
    assert "ferie_assenze" in tables


def test_dipendenti_crud(mem_conn):
    # Aggiungi
    ok, msg = ferie.add_dipendente(mem_conn, "Mario Rossi", "mario@azienda.it", totale_annuo=28.0)
    assert ok is True

    # Duplicato vietato
    ok_dup, _ = ferie.add_dipendente(mem_conn, "Mario Rossi")
    assert ok_dup is False

    df = ferie.get_dipendenti(mem_conn)
    assert len(df) == 1
    assert df.iloc[0]["nome"] == "Mario Rossi"
    assert df.iloc[0]["totale_annuo"] == 28.0

    # Aggiorna
    ok_up, _ = ferie.update_dipendente(
        mem_conn, "Mario Rossi", "Mario Rossi Modificato", "mario.nuovo@azienda.it", 30.0,
        {"mattina_inizio": "08:30", "mattina_fine": "12:30", "pomeriggio_inizio": "14:30", "pomeriggio_fine": "18:30"}
    )
    assert ok_up is True
    df_up = ferie.get_dipendenti(mem_conn)
    assert df_up.iloc[0]["nome"] == "Mario Rossi Modificato"
    assert df_up.iloc[0]["totale_annuo"] == 30.0
    assert df_up.iloc[0]["mattina_inizio"] == "08:30"

    # Soft delete
    ok_del, _ = ferie.delete_dipendente(mem_conn, "Mario Rossi Modificato")
    assert ok_del is True
    assert len(ferie.get_dipendenti(mem_conn, solo_attivi=True)) == 0
    assert len(ferie.get_dipendenti(mem_conn, solo_attivi=False)) == 1


def test_calcolo_giorni_lavorativi():
    # Lunedì 03/08/2026 a Venerdì 07/08/2026 -> 5 gg
    d1 = date(2026, 8, 3)
    d2 = date(2026, 8, 7)
    assert ferie.calcola_giorni_lavorativi_esatti(d1, d2) == 5

    # Con weekend: da Venerdì 07/08 a Lunedì 10/08 -> 2 gg (Ven + Lun)
    d3 = date(2026, 8, 10)
    assert ferie.calcola_giorni_lavorativi_esatti(d2, d3) == 2

    # Festivo nazionale: 25 Aprile 2026 (Sabato, ma testiamo 1 Maggio 2026 Venerdì)
    # 01/05/2026 è festa del lavoro (Venerdì)
    festa_lavoro = date(2026, 5, 1)
    assert ferie.calcola_giorni_lavorativi_esatti(festa_lavoro, festa_lavoro) == 0

    # Da Giovedì 30/04 a Lunedì 04/05 -> Gio 30 (lav), Ven 01 (festa), Sab/Dom (weekend), Lun 04 (lav) = 2 gg
    assert ferie.calcola_giorni_lavorativi_esatti(date(2026, 4, 30), date(2026, 5, 4)) == 2


def test_permessi_orari():
    orario = {
        "mattina_inizio": time(8, 0),
        "mattina_fine": time(12, 0),
        "pomeriggio_inizio": time(14, 0),
        "pomeriggio_fine": time(18, 0),
    }
    assert ferie.ore_giornaliere_previste(orario) == 8.0

    # Assente tutta la mattina (4 ore su 8) -> 0.5 giorni
    frazione = ferie.calcola_giorni_da_permesso_orario(
        orario,
        assente_mattina=True, ingresso_mattina=time(8, 0), uscita_mattina=time(12, 0),
        assente_pomeriggio=False, ingresso_pomeriggio=time(14, 0), uscita_pomeriggio=time(18, 0)
    )
    assert frazione == 0.5

    # Ritardo di 2 ore al mattino (ingresso 10:00) -> 2 ore su 8 = 0.25 giorni
    frazione_ritardo = ferie.calcola_giorni_da_permesso_orario(
        orario,
        assente_mattina=False, ingresso_mattina=time(10, 0), uscita_mattina=time(12, 0),
        assente_pomeriggio=False, ingresso_pomeriggio=time(14, 0), uscita_pomeriggio=time(18, 0)
    )
    # Test descrizioni testuali (es. Entrata posticipata / Uscita anticipata / Assente)
    desc_assente_m = ferie.descrivi_permesso_orario(
        orario,
        assente_mattina=True, ingresso_mattina=time(8, 0), uscita_mattina=time(12, 0),
        assente_pomeriggio=False, ingresso_pomeriggio=time(14, 0), uscita_pomeriggio=time(18, 0)
    )
    assert desc_assente_m == "Assente mattina"

    desc_uscita = ferie.descrivi_permesso_orario(
        orario,
        assente_mattina=False, ingresso_mattina=time(8, 0), uscita_mattina=time(12, 0),
        assente_pomeriggio=False, ingresso_pomeriggio=time(14, 0), uscita_pomeriggio=time(16, 30)
    )
    assert desc_uscita == "Uscita anticipata 16:30"

    desc_combinato = ferie.descrivi_permesso_orario(
        orario,
        assente_mattina=False, ingresso_mattina=time(9, 0), uscita_mattina=time(12, 0),
        assente_pomeriggio=False, ingresso_pomeriggio=time(14, 0), uscita_pomeriggio=time(16, 0)
    )
    assert desc_combinato == "Entrata posticipata 09:00 + Uscita anticipata 16:00"

    # Test chip icona e tooltip per Permesso Orario vs Ferie
    chip_ferie = ferie._chip_html({
        "nome": "Mario Rossi",
        "tipo": "Ferie",
        "inizio": date(2026, 8, 3),
        "fine": date(2026, 8, 7),
    })
    assert ">Mario</div>" in chip_ferie
    assert "title=\"Mario Rossi — Ferie" in chip_ferie
    assert "🕐" not in chip_ferie

    chip_permesso = ferie._chip_html({
        "nome": "Mario Rossi",
        "tipo": "Permesso Orario",
        "giorni": 0.25,
        "dettaglio": "Uscita anticipata 16:00",
        "inizio": date(2026, 8, 3),
        "fine": date(2026, 8, 3),
    })
    assert ">🕐 Mario</div>" in chip_permesso
    assert "title=\"🕐 Mario Rossi — Uscita anticipata 16:00\"" in chip_permesso


def test_ferie_assenze_crud_and_overlap(mem_conn):
    ferie.add_dipendente(mem_conn, "Luigi Bianchi")
    ferie.add_dipendente(mem_conn, "Anna Verdi")

    # Inserimento Luigi
    ok, _ = ferie.add_ferie(mem_conn, "Luigi Bianchi", date(2026, 7, 6), date(2026, 7, 10), "Ferie")
    assert ok is True

    # Luigi non può sovrapporsi a se stesso
    ok_self_overlap, msg = ferie.add_ferie(mem_conn, "Luigi Bianchi", date(2026, 7, 8), date(2026, 7, 15), "Ferie")
    assert ok_self_overlap is False
    assert "ha già un'assenza registrata" in msg

    # Controllo sovrapposizioni per Anna: rileva Luigi
    colleghi = ferie.check_overlaps(mem_conn, date(2026, 7, 8), date(2026, 7, 12), escludi_nome="Anna Verdi")
    assert "Luigi Bianchi" in colleghi

    # Storico
    df_st = ferie.get_ferie_storico(mem_conn)
    assert len(df_st) == 1
    assert df_st.iloc[0]["nome"] == "Luigi Bianchi"
    assert df_st.iloc[0]["giorni_lavorativi"] == 5.0


def test_calcolo_riepilogo_annuale():
    # Storico su più anni con riporto
    df_storico = pd.DataFrame([
        {"nome": "Mario", "data_inizio": "2025-06-01", "data_fine": "2025-06-10", "tipo": "Ferie", "giorni_lavorativi": 8.0},
        {"nome": "Mario", "data_inizio": "2026-07-01", "data_fine": "2026-07-15", "tipo": "Ferie", "giorni_lavorativi": 10.0},
    ])
    # Budget 26 gg
    # 2025: usati 8, disponibili 26, residuo 18
    # 2026: usati 10, disponibili 26 + 18 = 44, residuo 34
    riep = ferie.calcola_riepilogo_ferie_annuale(df_storico, "Mario", totale_annuo=26.0)

    assert 2025 in riep
    assert riep[2025]["usati"] == 8.0
    assert riep[2025]["residuo"] == 18.0

    assert 2026 in riep
    assert riep[2026]["usati"] == 10.0
    assert riep[2026]["disponibili"] == 44.0
    assert riep[2026]["residuo"] == 34.0


def test_formattazioni():
    assert ferie.formatta_giorni_ore(4.0) == "4g"
    assert ferie.formatta_giorni_ore(4.25) == "4g 2h"
    assert ferie.formatta_giorni_ore(0.0) == "0g"
    assert ferie.formatta_giorni_ore(-1.5) == "-1g 4h"
    assert ferie.formatta_data_lunga(date(2026, 8, 10)) == "10 Agosto 2026"


def test_nome_da_email():
    assert ferie.nome_da_email("mario.rossi@azienda.com") == "Mario Rossi"
    assert ferie.nome_da_email("laura_bianchi@domain.it") == "Laura Bianchi"
    assert ferie.nome_da_email("admin@test.org") == "Admin"
    assert ferie.nome_da_email("") == "Dipendente"


def test_sync_utenti_con_dipendenti(mem_conn):
    # Crea tabella utenti_ruoli e inserisce due utenti
    mem_conn.execute("""
    CREATE TABLE IF NOT EXISTS utenti_ruoli (
        email TEXT PRIMARY KEY,
        ruolo TEXT NOT NULL,
        assegnato_il TEXT NOT NULL
    );
    """)
    mem_conn.execute("INSERT INTO utenti_ruoli VALUES ('giuseppe.verdi@azienda.it', 'Finance', '2026-01-01T00:00:00Z')")
    mem_conn.execute("INSERT INTO utenti_ruoli VALUES ('elena.neri@azienda.it', 'Logistica', '2026-01-01T00:00:00Z')")
    mem_conn.commit()

    aggiunti = ferie.sync_utenti_con_dipendenti(mem_conn)
    assert aggiunti == 2

    df_dip = ferie.get_dipendenti(mem_conn)
    nomi = df_dip["nome"].tolist()
    assert "Giuseppe Verdi" in nomi
    assert "Elena Neri" in nomi
    assert (df_dip["totale_annuo"] == 31.0).all()

    # Rilancio sync non crea duplicati
    aggiunti_bis = ferie.sync_utenti_con_dipendenti(mem_conn)
    assert aggiunti_bis == 0


def test_parse_ora_robusto():
    # Stringhe con diversi formati
    assert ferie._parse_ora("07:00", "08:00") == time(7, 0)
    assert ferie._parse_ora("7:00", "08:00") == time(7, 0)
    assert ferie._parse_ora("07.30", "08:00") == time(7, 30)
    assert ferie._parse_ora("17:45:00", "08:00") == time(17, 45)
    # Oggetti time e datetime
    assert ferie._parse_ora(time(9, 15), "08:00") == time(9, 15)
    # Valori non validi o nan
    assert ferie._parse_ora(None, "08:00") == time(8, 0)
    assert ferie._parse_ora(float("nan"), "08:00") == time(8, 0)
    assert ferie._parse_ora("non_orario", "14:00") == time(14, 0)


def test_recupero_orari_esatti_dipendente(mem_conn):
    # Dipendente 1 con orario standard (08:00-12:00, 14:00-18:00)
    ferie.add_dipendente(
        mem_conn, "Dipendente Standard",
        mattina_inizio="08:00", mattina_fine="12:00",
        pomeriggio_inizio="14:00", pomeriggio_fine="18:00"
    )
    # Dipendente 2 con orario speciale (07:00-12:00, 14:00-17:00)
    ferie.add_dipendente(
        mem_conn, "Dipendente Speciale",
        mattina_inizio="07:00", mattina_fine="12:00",
        pomeriggio_inizio="14:00", pomeriggio_fine="17:00"
    )

    df = ferie.get_dipendenti(mem_conn)
    row_std = df[df["nome"] == "Dipendente Standard"].iloc[0]
    row_spe = df[df["nome"] == "Dipendente Speciale"].iloc[0]

    orario_std = ferie.get_orario_dipendente(row_std)
    orario_spe = ferie.get_orario_dipendente(row_spe)

    assert orario_std["mattina_inizio"] == time(8, 0)
    assert orario_std["pomeriggio_fine"] == time(18, 0)

    assert orario_spe["mattina_inizio"] == time(7, 0)
    assert orario_spe["pomeriggio_fine"] == time(17, 0)
    assert ferie.ore_giornaliere_previste(orario_spe) == 8.0

    # Test permesso con ritardo di 1 ora per orario speciale (ingresso ore 8:00 anziché 7:00)
    frazione = ferie.calcola_giorni_da_permesso_orario(
        orario_spe,
        assente_mattina=False, ingresso_mattina=time(8, 0), uscita_mattina=time(12, 0),
        assente_pomeriggio=False, ingresso_pomeriggio=time(14, 0), uscita_pomeriggio=time(17, 0)
    )
    # 1 ora mancante su 8 = 0.125
    assert frazione == 0.125


def test_preferenze_widget_homepage(mem_conn):
    from core import settings

    # Utente senza preferenze salvate -> default attivi
    pref = settings.get_user_home_widgets(mem_conn, "utente@falc.biz")
    assert pref["calendario_settimanale"] is True
    assert pref["aree_operative"] is True
    assert pref["stato_db"] is True

    # Salva preferenze personalizzate con ordinamento
    ok = settings.save_user_home_widgets_config(
        mem_conn, "utente@falc.biz",
        ordine=["stato_db", "aree_operative", "calendario_settimanale"],
        visibilita={"calendario_settimanale": False, "aree_operative": True, "stato_db": True}
    )
    assert ok is True

    # Ricarica e verifica persistenza di ordine e visibilità
    cfg_agg = settings.get_user_home_widgets_config(mem_conn, "utente@falc.biz")
    assert cfg_agg["ordine"] == ["stato_db", "aree_operative", "calendario_settimanale"]
    assert cfg_agg["visibilita"]["calendario_settimanale"] is False
    assert cfg_agg["visibilita"]["aree_operative"] is True
    assert cfg_agg["visibilita"]["stato_db"] is True


def test_budget_annuo_default_config(mem_conn):
    # Default iniziale è 31.0
    assert ferie.get_budget_annuo_default(mem_conn) == 31.0

    # Aggiornamento default
    ok = ferie.set_budget_annuo_default(mem_conn, 32.5)
    assert ok is True
    assert ferie.get_budget_annuo_default(mem_conn) == 32.5

    # Nuovo dipendente senza budget esplicito eredita il default configurato
    ok_add, _ = ferie.add_dipendente(mem_conn, "Nuovo Test")
    assert ok_add is True
    df_dip = ferie.get_dipendenti(mem_conn)
    row_nuovo = df_dip[df_dip["nome"] == "Nuovo Test"].iloc[0]
    assert row_nuovo["totale_annuo"] == 32.5

    # Applica a tutti i dipendenti attivi
    ok_all, n_mod = ferie.applica_budget_a_tutti_i_dipendenti(mem_conn, 35.0)
    assert ok_all is True
    assert n_mod >= 1
    df_agg = ferie.get_dipendenti(mem_conn)
    assert (df_agg["totale_annuo"] == 35.0).all()


def test_apptest_calendario_mensile(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "pages" / "24_Ferie_Calendario.py"), default_timeout=30)
    at.session_state["user_role"] = "Admin"
    at.run()
    assert not at.exception
    # Viene mostrato solamente il calendario mensile: niente segmented control di sezione
    assert len(at.segmented_control) == 0
    # Presenti i pulsanti mese precedente, oggi, mese successivo
    assert len(at.button) >= 3


def test_apptest_registra_ferie_e_permessi(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from datetime import time
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    # 1. Admin: ha il selettore dipendente e può scegliere chiunque
    at_admin = AppTest.from_file(str(root / "pages" / "25_Ferie_Registra.py"), default_timeout=30)
    at_admin.session_state["user_role"] = "Admin"
    at_admin.run()
    assert not at_admin.exception
    assert len(at_admin.selectbox) >= 1  # Selettore dipendente presente

    # Passa a Permesso orario
    at_admin.radio[0].set_value("Permesso orario (entrata/uscita)").run()
    assert not at_admin.exception
    # Verifica che siano presenti i time_input per mattina e pomeriggio
    assert len(at_admin.time_input) == 4

    # Seleziona Marco Ripari con orario 07:00 - 17:00
    at_admin.selectbox[0].set_value("Marco Ripari").run()
    assert not at_admin.exception
    assert at_admin.time_input[0].value == time(7, 0)
    assert at_admin.time_input[3].value == time(17, 0)

    # 2. Utente standard: dipendente bloccato sulla propria utenza
    at_user = AppTest.from_file(str(root / "pages" / "25_Ferie_Registra.py"), default_timeout=30)
    at_user.session_state["user_role"] = "Finance"
    at_user.session_state["user_email"] = "giampiero.mattei@azienda.it"
    at_user.run()
    assert not at_user.exception
    # Non deve esserci il selettore dipendente per l'utente non-admin
    assert not any(s.key == "reg_nome_dipendente" for s in at_user.selectbox)


def test_apptest_riepilogo_e_configurazioni(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from datetime import time
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    # 1. Riepilogo da Admin: presente il selettore dipendente e scheda personale
    at_riep_admin = AppTest.from_file(str(root / "pages" / "26_Ferie_Riepilogo.py"), default_timeout=30)
    at_riep_admin.session_state["user_role"] = "Admin"
    at_riep_admin.session_state["user_email"] = "admin@azienda.it"
    at_riep_admin.run()
    assert not at_riep_admin.exception
    assert any(s.key == "riepilogo_admin_sel" for s in at_riep_admin.selectbox)

    # 2. Riepilogo da utente standard: non mostra il selettore di tutti i dipendenti
    at_riep_user = AppTest.from_file(str(root / "pages" / "26_Ferie_Riepilogo.py"), default_timeout=30)
    at_riep_user.session_state["user_role"] = "Finance"
    at_riep_user.session_state["user_email"] = "giampiero.mattei@azienda.it"
    at_riep_user.run()
    assert not at_riep_user.exception
    # Nessun selettore globale di dipendente presente per l'utente non-admin
    assert not any(s.key == "riepilogo_admin_sel" for s in at_riep_user.selectbox)

    # 3. Configurazioni: blocco per non-admin
    at_cfg_user = AppTest.from_file(str(root / "pages" / "27_Ferie_Configurazioni.py"), default_timeout=30)
    at_cfg_user.session_state["user_role"] = "Finance"
    at_cfg_user.run()
    # Verifica errore accesso negato
    assert len(at_cfg_user.error) >= 1

    # 4. Configurazioni: consentito per Admin con i 4 tab
    at_cfg_admin = AppTest.from_file(str(root / "pages" / "27_Ferie_Configurazioni.py"), default_timeout=30)
    at_cfg_admin.session_state["user_role"] = "Admin"
    at_cfg_admin.run()
    assert not at_cfg_admin.exception
    assert len(at_cfg_admin.tabs) >= 4
    tab_labels = [t.label for t in at_cfg_admin.tabs]
    assert "Saldi & Disponibilità" in tab_labels
    assert "Gestione Dipendenti" in tab_labels
    assert "Dettaglio Storico" in tab_labels
    assert "Impostazioni" in tab_labels


def test_apptest_homepage_widgets(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "pages" / "00_Home.py"), default_timeout=30)
    at.run()
    assert not at.exception

    # Di default tutti e 3 i widget sono attivi
    labels = [c.label for c in at.checkbox]
    assert "Calendario Presenze Settimanale" in labels
    assert "Aree Operative" in labels
    assert "Stato Database & Dati" in labels

    # Modifica posizione: sposta Aree Operative in posizione 1 e Calendario in 2
    # at.selectbox ha i selettori di posizione
    at.selectbox[0].set_value(2)  # Calendario in pos 2
    at.selectbox[1].set_value(1)  # Aree operative in pos 1
    at.button[0].click().run()
    assert not at.exception

    # Verifica che la prima sezione sia ora Aree Operative
    sezioni = [m.value for m in at.markdown if "Aree Operative" in str(m.value) or "Calendario Presenze" in str(m.value)]
    assert len(sezioni) >= 2
    # Il primo deve essere Aree Operative
    assert "Aree Operative" in sezioni[0]

