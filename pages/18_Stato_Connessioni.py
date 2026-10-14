"""Pagina Stato Connessioni & Servizi (Export & Sistema).

Monitoraggio e diagnostica in tempo reale di tutti i servizi dell'applicazione:
- Server LLM locale (llama.cpp porta 8082)
- Modello Decisionale locale (Rizzo Flow porta 8017)
- Database locale SQLite (data/ecombi.db, integrità e tabelle)
- Sessione utente e autenticazione Supabase
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
import requests
import streamlit as st

from core import chatbot, db, ferie, roles
from core.design_system import metric_cards, page_setup, section

page_setup(
    "Stato Connessioni & Servizi", "🔌",
    "Monitoraggio e diagnostica in tempo reale di server AI locali, database SQLite e sessione"
)

# Controllo accessi RBAC (Riservato esclusivamente ad Admin)
user_role = st.session_state.get("user_role")
user_email = st.session_state.get("user_email", "")

if user_role != "Admin":
    st.error("⛔ Accesso Negato: questa pagina di diagnostica è riservata esclusivamente agli amministratori.")
    st.stop()

# ---------------------------------------------------------------------------
# Pulsante Aggiorna e Inizializzazione
# ---------------------------------------------------------------------------
col_title, col_btn = st.columns([3, 1], vertical_alignment="center")
with col_title:
    st.caption("Verifica lo stato di connettività dei microservizi, dei modelli locali e del database.")
with col_btn:
    if st.button("🔄 Aggiorna Connessioni", use_container_width=True):
        st.rerun()

# ---------------------------------------------------------------------------
# Rilevamento Stato Servizi
# ---------------------------------------------------------------------------
llm_url = st.session_state.get("llm_url", chatbot.DEFAULT_BASE_URL)
decision_url = st.session_state.get("decision_url", chatbot.DEFAULT_DECISION_URL)

# 1. Test LLM Server (8082)
t0_llm = time.perf_counter()
is_llm_online, active_llm_model, llm_models, llm_err = chatbot.check_llm_server(llm_url)
ping_llm = (time.perf_counter() - t0_llm) * 1000 if is_llm_online else None

# 2. Test Modello Decisionale (8017)
t0_dec = time.perf_counter()
is_dec_online, dec_model, dec_err = chatbot.check_decision_server(decision_url)
ping_dec = (time.perf_counter() - t0_dec) * 1000 if is_dec_online else None

# 3. Test Database SQLite
conn = db.connect()
db_path = Path("data/ecombi.db")
db_size_mb = (db_path.stat().st_size / (1024 * 1024)) if db_path.exists() else 0.0

try:
    c_check = conn.execute("PRAGMA integrity_check").fetchone()
    db_ok = bool(c_check and c_check[0] == "ok")
    db_journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
except Exception as e:
    db_ok = False
    db_journal = "error"

# ---------------------------------------------------------------------------
# Metric Cards di Sintesi
# ---------------------------------------------------------------------------
cards = [
    {
        "label": "Server LLM (8082)",
        "value": "🟢 Online" if is_llm_online else "🔴 Offline",
        "delta": f"{ping_llm:.0f} ms" if ping_llm else (llm_err[:18] if llm_err else "Non attivo"),
        "delta_good": is_llm_online,
    },
    {
        "label": "Decisionale (8017)",
        "value": "🟢 Online" if is_dec_online else "🔴 Offline",
        "delta": f"{ping_dec:.0f} ms" if ping_dec else "Non attivo",
        "delta_good": is_dec_online,
    },
    {
        "label": "Database SQLite",
        "value": "🟢 Integro" if db_ok else "🔴 Errore",
        "delta": f"{db_size_mb:.2f} MB (WAL)" if db_journal.lower() == "wal" else f"{db_size_mb:.2f} MB",
        "delta_good": db_ok,
    },
    {
        "label": "Sessione Attiva",
        "value": user_role or "Utente",
        "delta": user_email.split("@")[0] if "@" in user_email else user_email,
        "delta_good": True,
    },
]
metric_cards(cards)

st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tab di Diagnostica Dettagliata
# ---------------------------------------------------------------------------
tab_llm, tab_decision, tab_db, tab_session = st.tabs([
    "🤖 Server LLM (Porta 8082)",
    "⚖️ Modello Decisionale (Porta 8017)",
    "💾 Database SQLite",
    "🔐 Sessione & Sicurezza",
])

# ===========================================================================
# TAB 1: SERVER LLM (PORTA 8082)
# ===========================================================================
with tab_llm:
    section("Server Locale llama.cpp (OpenAI-compatible API)")
    col_l1, col_l2 = st.columns([3, 2])

    with col_l1:
        new_llm_url = st.text_input(
            "Indirizzo Endpoint LLM",
            value=llm_url,
            help="URL del server llama.cpp in ascolto su porta 8082",
        )
        if new_llm_url != llm_url:
            st.session_state["llm_url"] = new_llm_url
            st.rerun()

        if is_llm_online:
            st.success(f"**Connessione Stabilita:** Modello caricato `{active_llm_model}`")
            if ping_llm:
                st.caption(f"⚡ Latenza ping HTTP: **{ping_llm:.1f} ms**")
        else:
            st.error(f"**Impossibile connettersi al server LLM:** {llm_err}")
            st.info("Verifica che il servizio systemd sia attivo: `systemctl status qwen3.service`")

    with col_l2:
        st.markdown("**Specifiche di Configurazione:**")
        st.markdown("""
        - **Porta:** `8082`
        - **Backend:** `llama-server` (C++ nativo AVX-512 VNNI)
        - **Accelerazione Hardware:** Flash Attention ON, 16 Threads
        - **Prompt Caching:** Attivo (`--prompt-cache`)
        - **Fast-Path:** Token-skip su intenti strutturati
        """)

    st.markdown("---")
    st.markdown("##### 🧪 Test Rapido di Inferenza AI")
    test_prompt = st.text_input("Prompt di test", value="Ciao! Rispondi in una frase presentandoti brevemente.", key="llm_test_input")
    if st.button("🚀 Esegui Test Inferenza", disabled=not is_llm_online):
        with st.spinner("Generazione in corso dal modello locale..."):
            t_start = time.perf_counter()
            try:
                res = requests.post(
                    f"{llm_url.rstrip('/')}/v1/chat/completions",
                    json={
                        "model": active_llm_model or chatbot.DEFAULT_MODEL,
                        "messages": [
                            {"role": "system", "content": "Sei l'assistente virtuale aziendale EcomAnalysis."},
                            {"role": "user", "content": test_prompt},
                        ],
                        "temperature": 0.6,
                        "max_tokens": 150,
                    },
                    timeout=30,
                )
                t_dur = time.perf_counter() - t_start
                if res.status_code == 200:
                    data = res.json()
                    ans = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    t_tokens = usage.get("total_tokens", 0)
                    speed = (usage.get("completion_tokens", 0) / t_dur) if t_dur > 0 else 0
                    st.success(f"Risposta generata in **{t_dur:.2f}s** ({speed:.1f} token/s, {t_tokens} token totali)")
                    st.markdown(f"> {ans}")
                else:
                    st.error(f"Errore server HTTP {res.status_code}: {res.text}")
            except Exception as e:
                st.error(f"Errore durante l'inferenza: {e}")

# ===========================================================================
# TAB 2: MODELLO DECISIONALE (PORTA 8017)
# ===========================================================================
with tab_decision:
    section("Modello Decisionale Locale (Rizzo Flow)")
    col_d1, col_d2 = st.columns([3, 2])

    with col_d1:
        new_dec_url = st.text_input(
            "Indirizzo Endpoint Decisionale",
            value=decision_url,
            help="URL del server decisionale Rizzo Flow su porta 8017",
        )
        if new_dec_url != decision_url:
            st.session_state["decision_url"] = new_dec_url
            st.rerun()

        if is_dec_online:
            st.success(f"**Connessione Stabilita:** Modello decisionale `{dec_model}`")
            if ping_dec:
                st.caption(f"⚡ Latenza classificazione: **{ping_dec:.1f} ms**")
        else:
            st.warning(f"**Modello Decisionale Offline:** {dec_err or 'Server non raggiungibile'}")
            st.caption("Quando offline, il chatbot attiva per sicurezza la Thinking Mode completa.")

    with col_d2:
        st.markdown("**Ruolo nel Flusso:**")
        st.markdown("""
        - **Porta:** `8017`
        - **Scopo:** Classifica le richieste dell'utente prima dell'invocazione a Qwen.
        - **Ottimizzazione:** Per saluti, ringraziamenti e query semplici applica `/no_think`, abbattendo i tempi di risposta da 25s a **istante**.
        """)

    st.markdown("---")
    st.markdown("##### 🧪 Test Classificazione Thinking Mode")
    dec_test_input = st.text_input("Frase utente da classificare", value="Ciao, come stai?", key="dec_test_input")
    if st.button("⚖️ Testa Decisione", disabled=not is_dec_online):
        with st.spinner("Classificazione in corso..."):
            t_start = time.perf_counter()
            need_think, choice, info = chatbot.should_use_thinking(dec_test_input, base_url=decision_url)
            t_dur = (time.perf_counter() - t_start) * 1000
            if need_think:
                st.info(f"🧠 **Thinking Mode NECESSARIA** (Latenza: {t_dur:.1f}ms) — Scelta: `{choice}`")
            else:
                st.success(f"⚡ **Modalità Rapida (/no_think)** (Latenza: {t_dur:.1f}ms) — Scelta: `{choice}`")
            with st.expander("Dettagli grezzi classificazione", expanded=False):
                st.json(info)

# ===========================================================================
# TAB 3: DATABASE SQLITE
# ===========================================================================
with tab_db:
    section("Database Locale SQLite (`data/ecombi.db`)")
    col_db1, col_db2, col_db3 = st.columns(3)
    with col_db1:
        st.metric("Dimensione File", f"{db_size_mb:.2f} MB")
    with col_db2:
        st.metric("Stato Integrità", "OK" if db_ok else "ERRORE")
    with col_db3:
        st.metric("Journal Mode", db_journal.upper())

    # Calcolo metriche specifiche per righe (vendite vs resi) e anagrafica
    try:
        cnt_tot_righe = conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0]
        cnt_vendite = conn.execute("SELECT COUNT(*) FROM righe WHERE status = 'Spedito'").fetchone()[0]
        cnt_resi = conn.execute("SELECT COUNT(*) FROM righe WHERE status = 'Reso' OR data_reso IS NOT NULL").fetchone()[0]
    except Exception:
        cnt_tot_righe, cnt_vendite, cnt_resi = 0, 0, 0

    try:
        cnt_anagrafica = conn.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0]
    except Exception:
        cnt_anagrafica = 0

    try:
        cnt_correzioni = conn.execute("SELECT COUNT(*) FROM regole_correzione").fetchone()[0]
    except Exception:
        cnt_correzioni = 0

    st.markdown("---")
    st.markdown("##### 📦 Modulo Analisi Dati & Transazioni")
    st.info(
        "💡 **Architettura Dati EcomAnalysis:** Le vendite (**Dataset**) e i resi (**Resi**) sono conservati "
        "e riconciliati all'interno della tabella unificata ad alte prestazioni `righe`. Il catalogo articoli "
        "è gestito nella tabella `anagrafica` e le rettifiche manuali nella tabella `regole_correzione`."
    )

    c_d1, c_d2, c_d3, c_d4 = st.columns(4)
    with c_d1:
        st.metric("Totale Righe Transazioni", f"{cnt_tot_righe:,}".replace(",", "."))
    with c_d2:
        st.metric("Ordini Spediti (Vendite)", f"{cnt_vendite:,}".replace(",", "."))
    with c_d3:
        st.metric("Resi Riconciliati", f"{cnt_resi:,}".replace(",", "."))
    with c_d4:
        st.metric("Articoli in Anagrafica", f"{cnt_anagrafica:,}".replace(",", "."))

    st.markdown("---")
    st.markdown("##### 📊 Censimento Completo Tabelle del Database")

    # Mappa descrizioni delle tabelle di sistema
    DESCRIZIONI_TABELLE = {
        "righe": "Dataset Vendite e Resi (Tabella master transazioni e-commerce)",
        "anagrafica": "Anagrafica Articoli (Catalogo prodotti, SKU, Brand, Linee e Categorie)",
        "regole_correzione": "Correzioni Manuali DB (Regole di normalizzazione e correzione attiva)",
        "log_correzioni": "Log Correzioni (Storico delle modifiche applicate al dataset)",
        "upload_log": "Registro Upload (Storico dei file Dataset, Resi e Anagrafica caricati)",
        "log_match": "Log Riconciliazione (Tracciamento match tra ordini e flussi resi)",
        "impostazioni": "Configurazioni Aziendali (Anno fiscale, aliquote IVA e tassi di cambio)",
        "dipendenti": "Anagrafica Dipendenti (Orari di lavoro contrattuali e anagrafica)",
        "ferie_assenze": "Ferie & Permessi (Richieste ferie, permessi e assenze registrate)",
        "ferie_config": "Configurazioni Ferie (Parametri maturazione ferie e monte ore)",
        "agenda_eventi": "Agenda & Riunioni (Appuntamenti e impegni personali sincronizzati con il bot)",
        "chatbot_messaggi": "Cronologia Chat (Archivio messaggi scambiati con l'assistente AI)",
        "chatbot_memoria": "Memoria Chatbot (Preferenze personali e abitudini apprese a lungo termine)",
        "utenti_ruoli": "Ruoli Utente (Associazione email-ruolo RBAC)",
        "ruoli": "Definizione Ruoli (Admin, Finance, Logistica, ecc.)",
        "permessi_ruolo": "Permessi Ruoli (Autorizzazioni di accesso alle pagine per ruolo)",
        "utenti_preferenze": "Preferenze Utente (Configurazione widget e ordinamento homepage)",
        "regole_anagrafica": "Regole Anagrafica (Regole di arricchimento e mapping articoli)",
    }

    # Interrogazione dinamica delle tabelle realmente presenti nel DB SQLite
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tabelle_db = [r[0] for r in cursor.fetchall()]

    # Ordina con le tabelle core in primo piano
    priorita = ["righe", "anagrafica", "regole_correzione", "log_match", "upload_log", "log_correzioni",
                "impostazioni", "dipendenti", "ferie_assenze", "agenda_eventi", "chatbot_messaggi", "chatbot_memoria"]
    tabelle_ordinate = [t for t in priorita if t in tabelle_db] + [t for t in tabelle_db if t not in priorita]

    righe_stats = []
    for t_name in tabelle_ordinate:
        try:
            r = conn.execute(f"SELECT COUNT(*) FROM {t_name}").fetchone()
            count = r[0] if r else 0
            stato_tab = "🟢 Attiva"
        except Exception:
            count = 0
            stato_tab = "🔴 Errore"

        t_desc = DESCRIZIONI_TABELLE.get(t_name, "Tabella di sistema / applicazione")
        righe_stats.append({
            "Tabella": t_name,
            "Descrizione Funzionale": t_desc,
            "Record Censiti": f"{count:,}".replace(",", "."),
            "Stato": stato_tab,
        })

    import pandas as pd
    st.dataframe(pd.DataFrame(righe_stats), hide_index=True, use_container_width=True)

# ===========================================================================
# TAB 4: SESSIONE & SICUREZZA
# ===========================================================================
with tab_session:
    section("Sessione Utente Corrente & Sicurezza")
    col_s1, col_s2 = st.columns(2)

    with col_s1:
        st.markdown(f"**Email Utente:** `{user_email}`")
        st.markdown(f"**Ruolo di Sistema:** `{user_role}`")
        user_perms = st.session_state.get("user_permissions", [])
        st.markdown(f"**Pagine Abilitate per Ruolo:** `{len(user_perms)} pagine`")

    with col_s2:
        st.markdown("**Stato Autenticazione:**")
        st.success("🟢 Sessione Attiva e Valida (JWT/Cookie Persistente)")
        st.caption("I permessi e l'accesso ai moduli sono vincolati dal motore RBAC centralizzato.")
