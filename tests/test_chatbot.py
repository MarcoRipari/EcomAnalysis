"""Test unitari e AppTest per il modulo Chatbot e la gestione memoria utente."""
import sqlite3
import pytest
from streamlit.testing.v1 import AppTest

from core import chatbot, db, ferie, roles


@pytest.fixture
def memory_db():
    """Inizializza un database SQLite in memoria con schemi dipendenti e chatbot."""
    conn = sqlite3.connect(":memory:")
    roles.init_roles(conn)
    ferie.init_ferie_tables(conn)
    chatbot.init_chatbot_tables(conn)

    # Inserisci dipendente di test con orari definiti
    ferie.add_dipendente(
        conn,
        nome="Mario Rossi",
        email="mario.rossi@azienda.it",
        totale_annuo=31.0,
        mattina_inizio="08:30",
        mattina_fine="12:30",
        pomeriggio_inizio="14:30",
        pomeriggio_fine="18:30",
    )
    # Assegna ruolo
    roles.set_user_role(conn, "mario.rossi@azienda.it", "Finance")
    return conn


def test_chatbot_messaggi_crud(memory_db):
    conn = memory_db
    email = "mario.rossi@azienda.it"

    # Salva messaggi
    m1_id = chatbot.save_chat_message(conn, email, "user", "Ciao!")
    assert m1_id > 0
    m2_id = chatbot.save_chat_message(
        conn, email, "assistant", "Ciao Mario! Come posso aiutarti?", reasoning="Pensiero interno..."
    )
    assert m2_id > 0

    # Recupera cronologia
    history = chatbot.get_chat_history(conn, email)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Ciao!"
    assert history[1]["role"] == "assistant"
    assert history[1]["reasoning"] == "Pensiero interno..."

    # Cancella cronologia
    chatbot.clear_chat_history(conn, email)
    assert len(chatbot.get_chat_history(conn, email)) == 0


def test_chatbot_memoria_crud(memory_db):
    conn = memory_db
    email = "mario.rossi@azienda.it"

    # Salva memoria
    saved = chatbot.save_memoria(conn, email, "orario", "Inizio venerdì", "08:00")
    assert saved is True

    # Salva seconda memoria
    chatbot.save_memoria(conn, email, "preferenza", "Stile", "Sintetico")

    # Recupera memorie
    memorie = chatbot.get_user_memorie(conn, email)
    assert len(memorie) == 2
    assert any(m["chiave"] == "Inizio venerdì" and m["valore"] == "08:00" for m in memorie)

    # Aggiorna memoria esistente (UPSERT)
    chatbot.save_memoria(conn, email, "orario", "Inizio venerdì", "07:30")
    memorie_agg = chatbot.get_user_memorie(conn, email)
    assert len(memorie_agg) == 2
    match = [m for m in memorie_agg if m["chiave"] == "Inizio venerdì"][0]
    assert match["valore"] == "07:30"

    # Elimina singola memoria
    del_ok = chatbot.delete_memoria(conn, match["id"])
    assert del_ok is True
    assert len(chatbot.get_user_memorie(conn, email)) == 1

    # Clear memorie
    chatbot.clear_user_memorie(conn, email)
    assert len(chatbot.get_user_memorie(conn, email)) == 0


def test_get_user_context_e_system_prompt(memory_db):
    conn = memory_db
    email = "mario.rossi@azienda.it"

    # Aggiungi memoria
    chatbot.save_memoria(conn, email, "preferenza", "Caffè", "Espresso amaro")

    # Aggiungi assenze ferie e permessi orari per Mario Rossi
    from datetime import date
    oggi_y = date.today().year
    # Dal 6 al 10 luglio (lun-ven) = 5 giorni lavorativi
    ferie.add_ferie(conn, "Mario Rossi", date(oggi_y, 7, 6), date(oggi_y, 7, 10), tipo="Ferie")
    conn.execute(
        "INSERT INTO ferie_assenze (nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, creato_il) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Mario Rossi", f"{oggi_y}-09-01", f"{oggi_y}-09-01", "Permesso Orario", 0.5, "Uscita 14:00", "2026-09-01T10:00:00")
    )
    conn.commit()

    ctx = chatbot.get_user_context(conn, email)
    assert ctx["nome"] == "Mario Rossi"
    assert ctx["ruolo"] == "Finance"
    assert ctx["orari"]["mattina_inizio"] == "08:30"
    assert ctx["orari"]["pomeriggio_fine"] == "18:30"
    assert ctx["ferie"]["totale_annuo"] == 31.0
    assert ctx["ferie"]["godute"] == 5.5
    assert ctx["ferie"]["permessi_ore"] == 4.0
    assert ctx["ferie"]["residue"] == 25.5

    prompt = chatbot.build_system_prompt(conn, email)
    assert "Mario Rossi" in prompt
    assert "Finance" in prompt
    assert "08:30 - 12:30" in prompt
    assert "14:30 - 18:30" in prompt
    assert "25.50 giorni residui" in prompt
    assert "Espresso amaro" in prompt
    assert "LINGUA DI RAGIONAMENTO" in prompt
    assert "<memoria>" in prompt


def test_parse_reasoning_and_content():
    raw_with_cot = "<think>\nRagionamento in corso qui...\n</think>\n\nCiao! Tutto bene."
    cot, clean = chatbot.parse_reasoning_and_content(raw_with_cot)
    assert cot == "Ragionamento in corso qui..."
    assert clean == "Ciao! Tutto bene."

    raw_no_cot = "Solo risposta semplice."
    cot, clean = chatbot.parse_reasoning_and_content(raw_no_cot)
    assert cot == ""
    assert clean == "Solo risposta semplice."


def test_extract_and_save_memories(memory_db):
    conn = memory_db
    email = "mario.rossi@azienda.it"

    testo = """Certamente Mario, ho registrato tutto!

<memoria>
- [orario] Pausa pranzo: 13:00 - 14:00
- [preferenza] Notifiche: Solo urgenti
</memoria>

A presto!"""

    clean_text, extracted = chatbot.extract_and_save_memories(conn, email, testo)
    assert len(extracted) == 2
    assert "<memoria>" not in clean_text
    assert "Certamente Mario" in clean_text
    assert "A presto!" in clean_text

    # Verifica che siano nel DB
    memorie = chatbot.get_user_memorie(conn, email)
    assert len(memorie) == 2
    assert any(m["chiave"] == "Pausa pranzo" for m in memorie)
    assert any(m["chiave"] == "Notifiche" for m in memorie)


def test_page_99_test_chatbot_rbac_non_admin(tmp_path, monkeypatch):
    """Verifica che un utente non-admin venga bloccato all'accesso della pagina test."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(root))

    at = AppTest.from_file(str(root / "pages" / "99_Test_Chatbot.py"), default_timeout=30)
    at.session_state["user_role"] = "Finance"
    at.session_state["user_email"] = "utente@azienda.it"
    at.run()

    # Deve mostrare errore di accesso negato
    assert any("Accesso Negato" in str(e.value) for e in at.error)


def test_page_99_test_chatbot_admin_renders(tmp_path, monkeypatch):
    """Verifica che un utente Admin carichi la pagina test con successo."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(root))

    at = AppTest.from_file(str(root / "pages" / "99_Test_Chatbot.py"), default_timeout=30)
    at.session_state["user_role"] = "Admin"
    at.session_state["user_email"] = "admin@azienda.it"
    at.run()

    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 4


def test_chatbot_page_direct_fast_path(tmp_path, monkeypatch):
    """Verifica che la pagina 99_Test_Chatbot gestisca un prompt di tracking con direct fast path senza eccezioni."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(root))

    at = AppTest.from_file(str(root / "pages" / "99_Test_Chatbot.py"), default_timeout=30)
    at.session_state["user_role"] = "Admin"
    at.session_state["user_email"] = "admin@azienda.it"
    at.session_state["pending_prompt"] = "Traccia questo pacco UPS: 1Z46W1446843904912"
    at.run()

    assert not at.exception, [e.value for e in at.exception]


def test_format_qwen_prompt():
    # Se thinking mode NON è necessaria, aggiunge /no_think
    p1 = chatbot.format_qwen_prompt("Ciao!", need_thinking=False)
    assert p1 == "/no_think Ciao!"

    # Se /no_think è già presente, non lo duplica
    p2 = chatbot.format_qwen_prompt("/no_think Ciao!", need_thinking=False)
    assert p2 == "/no_think Ciao!"

    # Se thinking mode è necessaria, mantiene il prompt inalterato
    p3 = chatbot.format_qwen_prompt("Spiega l'algoritmo di Dijkstra", need_thinking=True)
    assert p3 == "Spiega l'algoritmo di Dijkstra"


def test_decision_server_check():
    # Verifica che check_decision_server ritorni un risultato coerente
    online, model, err = chatbot.check_decision_server("http://127.0.0.1:8017")
    if online:
        assert "Spark" in model or "rizzo" in model or len(model) > 0
    else:
        assert isinstance(err, str)


def test_should_use_thinking_live():
    # Se il server decisionale è online, verifica la risposta
    online, _, _ = chatbot.check_decision_server("http://127.0.0.1:8017")
    if online:
        # Un saluto semplice deve produrre need_thinking=False
        need_th, choice, details = chatbot.should_use_thinking("Ciao!", base_url="http://127.0.0.1:8017")
        assert need_th is False
        assert choice == "no"
        assert "probabilities" in details


def test_stream_chat_response_utf8(monkeypatch):
    """Verifica che lo streaming SSE decodifichi correttamente caratteri UTF-8 senza corromperli."""
    import io
    import json
    import requests

    testo_accentato = "Questo è un test con lettere accentate: à, è, é, ì, ò, ù!"
    sse_data = (
        f"data: {json.dumps({'choices': [{'delta': {'content': testo_accentato}}]})}\n\n"
        "data: [DONE]\n\n"
    ).encode("utf-8")

    class MockResponse:
        def __init__(self):
            self.encoding = None

        def raise_for_status(self):
            pass

        def iter_lines(self):
            # Restituisce righe bytes separate
            for line in sse_data.split(b"\n"):
                if line:
                    yield line

    def mock_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(requests, "post", mock_post)

    chunks = list(
        chatbot.stream_chat_response(
            "http://mock-url",
            "mock-model",
            [{"role": "user", "content": "test"}],
        )
    )
    risultato = "".join(chunks)
    assert risultato == testo_accentato
    assert "Ã" not in risultato


def test_stream_chat_response_reasoning_content(monkeypatch):
    """Verifica che lo streaming con delta reasoning_content venga formattato con i tag <think>."""
    import json
    import requests

    sse_lines = [
        f"data: {json.dumps({'choices': [{'delta': {'reasoning_content': 'Ragiono su questo punto.'}}]})}",
        f"data: {json.dumps({'choices': [{'delta': {'reasoning_content': ' Concludo il pensiero.'}}]})}",
        f"data: {json.dumps({'choices': [{'delta': {'content': 'Ecco la risposta finale!'}}]})}",
        "data: [DONE]",
    ]
    raw_payload = "\n\n".join(sse_lines).encode("utf-8")

    class MockResponse:
        def __init__(self):
            self.encoding = None

        def raise_for_status(self):
            pass

        def iter_lines(self):
            for line in raw_payload.split(b"\n"):
                if line:
                    yield line

    monkeypatch.setattr(requests, "post", lambda *a, **kw: MockResponse())

    chunks = list(
        chatbot.stream_chat_response(
            "http://mock-url",
            "mock-model",
            [{"role": "user", "content": "test"}],
        )
    )
    full = "".join(chunks)
    assert "<think>" in full
    assert "</think>" in full
    assert "Ragiono su questo punto." in full
    assert "Ecco la risposta finale!" in full


def test_agenda_crud_e_isolamento(memory_db):
    """Verifica il corretto funzionamento del modulo agenda con isolamento tra utenti."""
    from core import agenda

    conn = memory_db
    agenda.init_agenda_tables(conn)

    user1 = "mario.rossi@azienda.it"
    user2 = "luigi.verdi@azienda.it"

    # Creazione eventi per user1
    r1 = agenda.crea_evento(
        conn,
        user1,
        titolo="Riunione Fornitori",
        data_inizio="2026-10-15 10:00",
        data_fine="2026-10-15 11:30",
        luogo="Sala A",
        categoria="riunione",
        note="Portare report Q3",
    )
    assert r1["success"] is True
    ev1_id = r1["evento_id"]

    # Creazione evento per user2
    r2 = agenda.crea_evento(
        conn,
        user2,
        titolo="Audit Sicurezza",
        data_inizio="2026-10-16 14:00",
        categoria="lavoro",
    )
    assert r2["success"] is True
    ev2_id = r2["evento_id"]

    # Verifica isolamento: user1 non vede eventi di user2
    evs_user1 = agenda.get_eventi_utente(conn, user1)
    assert len(evs_user1) == 1
    assert evs_user1[0]["id"] == ev1_id
    assert evs_user1[0]["titolo"] == "Riunione Fornitori"

    evs_user2 = agenda.get_eventi_utente(conn, user2)
    assert len(evs_user2) == 1
    assert evs_user2[0]["id"] == ev2_id

    # Completamento
    comp_res = agenda.segna_completato(conn, user1, ev1_id, completato=True)
    assert comp_res["success"] is True
    evs_attivi_u1 = agenda.get_eventi_utente(conn, user1, solo_attivi=True)
    assert len(evs_attivi_u1) == 0

    # User1 non può eliminare evento di user2
    del_wrong = agenda.elimina_evento(conn, user1, ev2_id)
    assert del_wrong["success"] is False

    # Eliminazione corretta
    del_ok = agenda.elimina_evento(conn, user1, ev1_id)
    assert del_ok["success"] is True
    assert len(agenda.get_eventi_utente(conn, user1)) == 0


def test_agenda_tool_dispatcher(memory_db):
    """Verifica il dispatcher esegui_tool_agenda per tutte le operazioni previste."""
    from core import agenda

    conn = memory_db
    agenda.init_agenda_tables(conn)
    email = "mario.rossi@azienda.it"

    # 1. Inserisci impegno via tool
    res_ins = agenda.esegui_tool_agenda(
        conn,
        email,
        "agenda_inserisci_impegno",
        {"titolo": "Call con Marco", "data_inizio": "2026-10-18 09:30", "categoria": "chiamata"},
    )
    assert res_ins["success"] is True
    ev_id = res_ins["evento_id"]

    # 2. Visualizza impegni via tool
    res_vis = agenda.esegui_tool_agenda(
        conn,
        email,
        "agenda_visualizza_impegni",
        {"data_da": "2026-10-18", "solo_attivi": True},
    )
    assert res_vis["success"] is True
    assert res_vis["totale_trovati"] == 1
    assert res_vis["eventi"][0]["id"] == ev_id

    # 3. Completa impegno via tool
    res_comp = agenda.esegui_tool_agenda(
        conn,
        email,
        "agenda_completa_impegno",
        {"evento_id": ev_id},
    )
    assert res_comp["success"] is True

    # 4. Elimina impegno via tool
    res_del = agenda.esegui_tool_agenda(
        conn,
        email,
        "agenda_elimina_impegno",
        {"evento_id": ev_id},
    )
    assert res_del["success"] is True

    # 5. Funzione inesistente
    res_unk = agenda.esegui_tool_agenda(
        conn,
        email,
        "tool_fantasma",
        {},
    )
    assert res_unk["success"] is False


def test_chat_turn_with_tools_mock(memory_db, monkeypatch):
    """Simula una chiamata tool dell'LLM e la successiva risposta finale in streaming."""
    import requests
    from core import agenda, chatbot

    conn = memory_db
    agenda.init_agenda_tables(conn)
    email = "mario.rossi@azienda.it"

    call_count = 0

    class MockStreamingToolCallResponse:
        def __init__(self):
            self.encoding = None

        def raise_for_status(self):
            pass

        def iter_lines(self):
            chunk = (
                b'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_123", "function": {"name": "agenda_inserisci_impegno", "arguments": "{\\"titolo\\": \\"Riunione di lavoro\\", \\"data_inizio\\": \\"2026-10-20 15:00\\"}"}}]}}]}\n\n'
                b'data: [DONE]\n\n'
            )
            for line in chunk.split(b"\n"):
                if line:
                    yield line

    class MockStreamingFinalResponse:
        def __init__(self):
            self.encoding = None

        def raise_for_status(self):
            pass

        def iter_lines(self):
            chunk = (
                b'data: {"choices": [{"delta": {"content": "Ho fissato il pranzo in agenda."}}]}\n\n'
                b'data: [DONE]\n\n'
            )
            for line in chunk.split(b"\n"):
                if line:
                    yield line

    def mock_post(url, json=None, stream=False, **kwargs):
        nonlocal call_count
        call_count += 1
        if json and "tools" in json:
            # Primo turno in streaming: emissione dei chunks tool call
            return MockStreamingToolCallResponse()
        else:
            # Secondo turno in streaming: risposta finale
            return MockStreamingFinalResponse()

    monkeypatch.setattr(requests, "post", mock_post)

    events_before = agenda.get_eventi_utente(conn, email)
    assert len(events_before) == 0

    events = list(
        chatbot.chat_turn_with_tools(
            base_url="http://mock-url",
            model="mock-model",
            messages=[{"role": "user", "content": "Aggiungi riunione alle 15"}],
            conn=conn,
            user_email=email,
        )
    )

    tool_calls = [d for t, d in events if t == "tool_call"]
    tool_results = [d for t, d in events if t == "tool_result"]
    chunks = [d for t, d in events if t == "chunk"]

    full_resp = "".join(chunks)
    assert "Impegno Registrato con Successo!" in full_resp
    assert call_count == 1
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "agenda_inserisci_impegno"
    assert len(tool_results) == 1
    assert tool_results[0]["result"]["success"] is True

    # Verifica che l'evento sia stato effettivamente registrato nel DB
    events_after = agenda.get_eventi_utente(conn, email)
    assert len(events_after) == 1



def test_compact_chat_history():
    history = [
        {"role": "user", "content": "Messaggio 1 vecchio"},
        {"role": "assistant", "content": "Risposta 1 vecchia"},
        {"role": "user", "content": "Messaggio 2 vecchio"},
        {"role": "assistant", "content": "Risposta 2 vecchia con tabella:\n| Col1 | Col2 |\n| :--- | :--- |\n| Val1 | Val2 |\nNota finale."},
        {"role": "user", "content": "Quali sono i miei orari?"},
        {
            "role": "assistant",
            "content": "I tuoi orari sono 08:00 - 12:00.\n<div style='font-size:0.75rem'>⏱️ 1.2s</div>",
        },
    ]

    # Compatta agli ultimi 2 messaggi
    res_2 = chatbot.compact_chat_history(history, max_messages=2)
    assert len(res_2) == 2
    assert res_2[0]["role"] == "user"
    assert res_2[0]["content"] == "Quali sono i miei orari?"
    assert res_2[1]["role"] == "assistant"
    assert "⏱️" not in res_2[1]["content"]
    assert "08:00 - 12:00" in res_2[1]["content"]

    # Compatta agli ultimi 4 messaggi
    res_4 = chatbot.compact_chat_history(history, max_messages=4)
    assert len(res_4) == 4
    # Verifica che la griglia markdown sia stata rimossa
    tab_msg = res_4[1]["content"]
    assert "| Col1 |" not in tab_msg
    assert "Nota finale." in tab_msg

    # Test con cronologia vuota
    assert chatbot.compact_chat_history([]) == []
