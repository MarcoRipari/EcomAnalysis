"""Pagina TEST Chatbot con LLM locale (llama.cpp) e gestione memoria utente.

Funzionalità:
- Riservata esclusivamente all'Admin (fuori da tutti i menu, posizionata in fondo alla sidebar).
- Dialogo con server llama.cpp locale (default: http://127.0.0.1:8082, modello Qwen3-8B-Q4_K_M.gguf).
- Chat isolata per ogni utente con persistenza su SQLite.
- Riconoscimento utente: nome, ruolo RBAC, orari di lavoro contrattuali, ferie residue.
- Memoria persistente a lungo termine (preferenze, abitudini, orari personalizzati).
- Apprendimento automatico da conversazione (tag <memoria>...</memoria>).
- Separazione trasparente del ragionamento CoT (tag <think>...</think> di Qwen3).
- Gestione interattiva della memoria (visualizzazione, aggiunta, eliminazione).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
import pandas as pd
import streamlit as st

from core import agenda, assistant_tools, chatbot, db, ferie, roles
from core.design_system import page_setup

# Inizializzazione pagina e tema aziendale
from core.design_system import apply_theme
st.set_page_config(page_title="Chatbot AI", page_icon="🤖", layout="wide")
apply_theme()

# CSS per l'animazione fluida dei puntini "Sto pensando..." (100% clientside, zero scatti o chiusure)
st.markdown("""
<style>
@keyframes thinkingDots {
    0%   { content: ''; }
    25%  { content: '.'; }
    50%  { content: '..'; }
    75%  { content: '...'; }
    100% { content: ''; }
}
div[data-testid="stExpander"] summary em::after {
    display: inline-block;
    content: '...';
    animation: thinkingDots 1.4s infinite;
    width: 1.5em;
    text-align: left;
    margin-left: 2px;
}
</style>
""", unsafe_allow_html=True)

# Controllo di sicurezza RBAC (Accesso rigorosamente riservato agli Admin)
user_role = st.session_state.get("user_role")
user_email_loggato = st.session_state.get("user_email", "")

if user_role != "Admin":
    st.error("⛔ Accesso Negato: questa pagina sperimentale è riservata esclusivamente agli amministratori.")
    st.stop()

# Connessione DB e inizializzazione tabelle
conn = db.connect()
chatbot.init_chatbot_tables(conn)
ferie.init_ferie_tables(conn)
agenda.init_agenda_tables(conn)

# ---------------------------------------------------------------------------
# Parametri Operativi LLM & Decisionale
# (Lo stato delle connessioni e la configurazione server sono gestiti in Export & Sistema → Stato Connessioni)
# ---------------------------------------------------------------------------
llm_url = st.session_state.get("llm_url", chatbot.DEFAULT_BASE_URL)
decision_url = st.session_state.get("decision_url", chatbot.DEFAULT_DECISION_URL)
model_choice = st.session_state.get("active_model", chatbot.DEFAULT_MODEL)
temperature = 0.7
max_tokens = 350
mostra_thinking = True
usa_tools = True
usa_decisionale = True

# ---------------------------------------------------------------------------
# Selezione Utente (Profilo Chat & Memoria)
# ---------------------------------------------------------------------------
# Recupero lista utenti/dipendenti censiti per permettere all'admin di testare qualsiasi profilo
df_dip = ferie.get_dipendenti(conn, solo_attivi=False)
lista_utenti: list[dict[str, str]] = []

if not df_dip.empty:
    for _, row in df_dip.iterrows():
        em = (row.get("email") or "").strip()
        nm = row.get("nome") or em
        if em:
            lista_utenti.append({"email": em.lower(), "nome": nm, "label": f"{nm} ({em})"})

# Aggiungi l'utente loggato se non già presente
if user_email_loggato and not any(u["email"] == user_email_loggato.lower() for u in lista_utenti):
    lista_utenti.insert(0, {
        "email": user_email_loggato.lower(),
        "nome": ferie.nome_da_email(user_email_loggato),
        "label": f"{ferie.nome_da_email(user_email_loggato)} ({user_email_loggato})",
    })

opzioni_labels = [u["label"] for u in lista_utenti]
indice_default = 0
for idx, u in enumerate(lista_utenti):
    if u["email"] == user_email_loggato.lower():
        indice_default = idx
        break

# Header compatto con titolo e selettore profilo utente sulla stessa riga (zero spazio sprecato)
c_title, c_user = st.columns([2.0, 1.2], vertical_alignment="center")
with c_title:
    st.markdown(
        '<div style="display: flex; align-items: center; gap: 12px; margin: 2px 0 6px 0;">'
        '<div class="ds-icon" style="width: 40px; height: 40px; font-size: 22px;">🤖</div>'
        '<div><h1 style="font-size: 1.45rem; font-weight: 800; margin: 0; line-height: 1.2;">Chatbot AI</h1>'
        '<p class="ds-sub" style="margin: 0; font-size: 0.82rem;">Assistente aziendale con memoria a lungo termine e gestione agenda</p>'
        '</div></div>',
        unsafe_allow_html=True,
    )

with c_user:
    sel_label = st.selectbox(
        "Profilo Utente Attivo",
        options=opzioni_labels,
        index=indice_default if opzioni_labels else 0,
        label_visibility="collapsed",
        help="L'Admin può simulare la chat e la memoria di qualsiasi utente aziendale.",
    )

# Determina l'email dell'utente selezionato
utente_target = lista_utenti[opzioni_labels.index(sel_label)] if opzioni_labels else {
    "email": user_email_loggato,
    "nome": "Admin",
}
email_attiva = utente_target["email"]

# Recupera contesto completo dell'utente selezionato
ctx = chatbot.get_user_context(conn, email_attiva)

# ---------------------------------------------------------------------------
# Tab Principali: Chat | Agenda Personale | Memoria Appresa | Debug System Prompt
# ---------------------------------------------------------------------------
eventi_agenda_tot = agenda.get_eventi_utente(conn, email_attiva)
tab_chat, tab_agenda, tab_memoria, tab_debug = st.tabs([
    "💬 Conversazione",
    f"📅 Agenda Personale ({len(eventi_agenda_tot)})",
    f"🧠 Memoria & Preferenze ({len(ctx['memorie'])})",
    "🔍 System Prompt & Debug",
])

# ===========================================================================
# TAB 1: CONVERSAZIONE CHAT
# ===========================================================================
with tab_chat:
    # Cronologia messaggi
    cronologia = chatbot.get_chat_history(conn, email_attiva, limit=60)

    # Container scrollabile dedicato per la cronologia chat (box con scroll interno)
    chat_container = st.container(height=600)

    with chat_container:
        if not cronologia:
            st.info(
                f"👋 Nessun messaggio precedente per **{ctx['nome']}**. "
                "Invia una domanda o una richiesta: il bot riconoscerà i tuoi orari, gestirà la tua agenda e apprenderà le tue preferenze!"
            )
        else:
            for msg in cronologia:
                role = msg["role"]
                content = msg["content"]
                reasoning = msg["reasoning"]

                with st.chat_message(role):
                    if role == "assistant" and reasoning and mostra_thinking:
                        with st.expander("💭 Pensiero completato (clicca per visualizzare)", expanded=False):
                            st.markdown(reasoning)
                    st.markdown(content, unsafe_allow_html=True)

    # Prompt rapidi di test (selezionabili con un click)
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    c_p1, c_p2, c_p3, c_p4 = st.columns(4)
    with c_p1:
        if st.button("📅 Fissa riunione domani alle 10", use_container_width=True):
            st.session_state["pending_prompt"] = "Fissami una riunione con il team logistica per domani alle 10:00."
            st.rerun()
    with c_p2:
        if st.button("📋 Cosa ho in agenda?", use_container_width=True):
            st.session_state["pending_prompt"] = "Quali appuntamenti e impegni ho in agenda nei prossimi giorni?"
            st.rerun()
    with c_p3:
        if st.button("⏰ Quali sono i miei orari?", use_container_width=True):
            st.session_state["pending_prompt"] = "Quali sono i miei orari di lavoro contrattuali e la pausa pranzo?"
            st.rerun()
    with c_p4:
        if st.button("🏖️ Quante ferie ho?", use_container_width=True):
            st.session_state["pending_prompt"] = "Quanti giorni di ferie mi restano quest'anno?"
            st.rerun()

    c_b1, c_b2, c_b3, c_b4 = st.columns(4)
    with c_b1:
        if st.button("👥 Buco con Giampiero", use_container_width=True):
            st.session_state["pending_prompt"] = "Trova uno slot libero domani insieme a Giampiero Mattei."
            st.rerun()
    with c_b2:
        if st.button("🔍 Chi è in ferie a Ottobre?", use_container_width=True):
            st.session_state["pending_prompt"] = "C'è qualcuno in ferie tra il 20 e il 25 Ottobre?"
            st.rerun()
    with c_b3:
        if st.button("📊 Fatturato Settembre 2026", use_container_width=True):
            st.session_state["pending_prompt"] = "Quanto abbiamo fatturato a Settembre 2026?"
            st.rerun()
    with c_b4:
        if st.button("🚚 Traccia pacco GLS", use_container_width=True):
            st.session_state["pending_prompt"] = "Traccia questo pacco GLS: AX000012849IT"
            st.rerun()

    # Input utente da barra di chat
    user_input = st.chat_input("Scrivi un messaggio per il chatbot...")

    # Recupera eventuale prompt pendente dai bottoni rapidi
    prompt_da_inviare = user_input or st.session_state.pop("pending_prompt", None)

    if prompt_da_inviare:
        t_request_start = time.time()
        is_online, _, _, err_msg = chatbot.check_llm_server(llm_url)
        if not is_online:
            st.error(f"Impossibile inviare il messaggio: il server LLM non è raggiungibile ({err_msg}). Verifica lo stato in **Export & Sistema → Stato Connessioni**.")
        else:
            # 1. Salva messaggio utente nel database (messaggio originale pulito)
            chatbot.save_chat_message(conn, email_attiva, "user", prompt_da_inviare)

            # 2. Mostra subito il messaggio dell'utente nella UI
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(prompt_da_inviare)

            # 2a. Verifica Fast-Path Diretto Istantaneo (es. Tracking pacco UPS/GLS o Saldo rapido senza LLM)
            direct_fast_resp = assistant_tools.detect_direct_fast_path(prompt_da_inviare, conn=conn, user_email=email_attiva)
            if direct_fast_resp:
                t_tot = time.time() - t_request_start
                footer = f"\n\n<div style='font-size: 0.74rem; color: #64748B; margin-top: 8px; border-top: 1px solid rgba(148, 163, 184, 0.2); padding-top: 4px; display: inline-block;'>⚡ <b>Fast-Path Istantaneo</b> &nbsp;·&nbsp; ⏱️ <b>{t_tot*1000:.1f}ms</b></div>"
                full_direct_msg = direct_fast_resp + footer
                chatbot.save_chat_message(conn, email_attiva, "assistant", full_direct_msg)
                st.rerun()

            # 2b. Valutazione con modello decisionale (porta 8017)
            need_thinking = False
            prompt_per_qwen = prompt_da_inviare
            decision_info = {}
            detected_intent = None
            scoped_tools = None

            is_dec_online, dec_model_name, _ = chatbot.check_decision_server(decision_url)
            if usa_decisionale and is_dec_online:
                # Classificazione trasparente in background: determina sia l'intent per lo scoping dei tool sia se serve il thinking
                dec_result = chatbot.classify_intent_and_routing(
                    prompt_da_inviare, base_url=decision_url
                )
                detected_intent = dec_result.get("intent", "chat")
                need_thinking = dec_result.get("need_thinking", False)
                scoped_tools = assistant_tools.get_scoped_tools_schema(prompt_da_inviare, intent=detected_intent)

                if "qwen3.5" in model_choice.lower():
                    prompt_per_qwen = prompt_da_inviare
                else:
                    prompt_per_qwen = chatbot.format_qwen_prompt(prompt_da_inviare, need_thinking)

                st.session_state["last_decision"] = {
                    "prompt": prompt_da_inviare,
                    "intent": detected_intent,
                    "need_thinking": need_thinking,
                    "tools_count": len(scoped_tools) if scoped_tools else 0,
                    "prompt_qwen": prompt_per_qwen,
                    "details": dec_result,
                }
            else:
                scoped_tools = assistant_tools.get_scoped_tools_schema(prompt_da_inviare)


            # 3. Costruisci il system prompt con profilo aggiornato e memorie
            sys_prompt = chatbot.build_system_prompt(conn, email_attiva)

            # Prepara cronologia recente per il modello compattata per mantenere l'inferenza ultra-rapida
            messages_payload = [{"role": "system", "content": sys_prompt}]
            messages_payload.extend(chatbot.compact_chat_history(cronologia, max_messages=4))
            messages_payload.append({"role": "user", "content": prompt_per_qwen})

            # 4. Genera risposta in streaming dall'LLM locale con pensiero <think> animato
            with chat_container:
                with st.chat_message("assistant"):
                    thinking_container = st.empty()
                    thought_placeholder = None
                    response_placeholder = None

                    # Messaggio di attesa con puntini animati senza expander (attivo durante elaborazione)
                    thinking_container.markdown(
                        """
                        <div style="display: flex; align-items: center; gap: 8px; color: #64748B; font-style: italic; margin-bottom: 8px;">
                            <span>💭 Sto pensando</span>
                            <span class="thinking-dots"><span>.</span><span>.</span><span>.</span></span>
                        </div>
                        <style>
                        @keyframes dot-blink {
                            0% { opacity: 0.15; }
                            30% { opacity: 1; }
                            100% { opacity: 0.15; }
                        }
                        .thinking-dots span {
                            animation: dot-blink 1.4s infinite both;
                            font-size: 1.3rem;
                            font-weight: 700;
                            line-height: 1;
                        }
                        .thinking-dots span:nth-child(2) { animation-delay: 0.25s; }
                        .thinking-dots span:nth-child(3) { animation-delay: 0.5s; }
                        </style>
                        """,
                        unsafe_allow_html=True,
                    )

                    in_think = False
                    think_ended = False
                    thinking_tokens: list[str] = []
                    response_tokens: list[str] = []

                    try:
                        if usa_tools and scoped_tools is not None:
                            gen_source = chatbot.chat_turn_with_tools(
                                base_url=llm_url,
                                model=model_choice,
                                messages=messages_payload,
                                conn=conn,
                                user_email=email_attiva,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                tools=scoped_tools,
                                enable_thinking=need_thinking,
                            )

                        else:
                            def _gen_raw():
                                for raw_ck in chatbot.stream_chat_response(
                                    base_url=llm_url,
                                    model=model_choice,
                                    messages=messages_payload,
                                    temperature=temperature,
                                    max_tokens=max_tokens,
                                    enable_thinking=need_thinking,
                                ):
                                    yield ("chunk", raw_ck)
                            gen_source = _gen_raw()

                        tool_notice_holder = None
                        buffer = ""
                        captured_metrics: dict[str, Any] = {}

                        for ev_type, ev_data in gen_source:
                            if ev_type == "tool_call":
                                thinking_container.empty()
                                if tool_notice_holder is None:
                                    tool_notice_holder = st.empty()
                                with tool_notice_holder.container():
                                    st.info(f"📅 **Azione Agenda Richiesta:** `{ev_data['name']}`\n\n```json\n{json.dumps(ev_data['args'], ensure_ascii=False, indent=2)}\n```")
                                continue
                            elif ev_type == "tool_result":
                                continue
                            elif ev_type == "metrics":
                                if isinstance(ev_data, dict):
                                    captured_metrics.update(ev_data)
                                continue
                            elif ev_type == "chunk":
                                chunk = ev_data
                                buffer += chunk

                                # Rilevamento inizio blocco <think>
                                if not in_think and not think_ended:
                                    if "<think>" in buffer:
                                        in_think = True
                                        thinking_container.empty()
                                        before_think, after_think = buffer.split("<think>", 1)
                                        if before_think.strip():
                                            response_tokens.append(before_think)
                                        buffer = after_think
                                    else:
                                        # Se non c'è <think>, non appena arrivano token reali rimuovi lo stato di attesa
                                        if (len(buffer) > 0 and not buffer.startswith("<")) or len(buffer) > 10:
                                            thinking_container.empty()
                                            think_ended = True
                                            if response_placeholder is None:
                                                response_placeholder = st.empty()
                                            response_tokens.append(buffer)
                                            response_placeholder.markdown("".join(response_tokens) + "▌")
                                            buffer = ""

                                # Gestione dentro il blocco <think>
                                if in_think:
                                    if "</think>" in buffer:
                                        thought_part, after_think_close = buffer.split("</think>", 1)
                                        thinking_tokens.append(thought_part)
                                        in_think = False
                                        think_ended = True

                                        full_thought_now = "".join(thinking_tokens).strip()
                                        thinking_container.empty()
                                        if full_thought_now and mostra_thinking:
                                            with thinking_container.container():
                                                with st.expander("💭 Pensiero completato (clicca per visualizzare)", expanded=False):
                                                    st.markdown(full_thought_now)

                                        buffer = after_think_close
                                        if response_placeholder is None:
                                            response_placeholder = st.empty()
                                        if buffer:
                                            response_tokens.append(buffer)
                                            response_placeholder.markdown("".join(response_tokens) + "▌")
                                            buffer = ""
                                    else:
                                        thinking_tokens.append(buffer)
                                        buffer = ""

                                        accumulated_thought = "".join(thinking_tokens)
                                        if mostra_thinking and accumulated_thought.strip():
                                            if thought_placeholder is None:
                                                with thinking_container.container():
                                                    exp = st.expander("💭 *Sto pensando*", expanded=False)
                                                    with exp:
                                                        thought_placeholder = st.empty()
                                            if thought_placeholder:
                                                thought_placeholder.markdown(accumulated_thought + "▌")

                                elif think_ended:
                                    if buffer:
                                        response_tokens.append(buffer)
                                        buffer = ""
                                        if response_placeholder is None:
                                            response_placeholder = st.empty()
                                        response_placeholder.markdown("".join(response_tokens) + "▌")

                        if buffer:
                            if in_think:
                                thinking_tokens.append(buffer)
                            else:
                                response_tokens.append(buffer)

                        if in_think:
                            full_thought_now = "".join(thinking_tokens).strip()
                            thinking_container.empty()
                            if full_thought_now and mostra_thinking:
                                with thinking_container.container():
                                    with st.expander("💭 Pensiero completato (clicca per visualizzare)", expanded=False):
                                        st.markdown(full_thought_now)

                    except Exception as exc:
                        st.error(f"Errore durante la generazione della risposta: {exc}")

                    t_request_end = time.time()
                    elapsed_time = max(0.01, t_request_end - t_request_start)

                    full_thinking = "".join(thinking_tokens).strip()
                    raw_accumulated_response = "".join(response_tokens).strip()

                    # Calcolo metriche reali (token, tps, latenza end-to-end)
                    pred_tokens = captured_metrics.get("predicted_n")
                    if pred_tokens and pred_tokens > 0:
                        tot_tokens = pred_tokens
                        tps = tot_tokens / elapsed_time
                    else:
                        full_text = (full_thinking + "\n" + raw_accumulated_response).strip()
                        tot_tokens = max(1, round(len(full_text) / 3.6))
                        tps = tot_tokens / elapsed_time

                    metrics_footer = (
                        f"\n\n<div style='font-size: 0.74rem; color: #64748B; margin-top: 8px; "
                        f"border-top: 1px solid rgba(148, 163, 184, 0.2); padding-top: 4px; display: inline-block;'>"
                        f"⏱️ <b>{elapsed_time:.2f}s</b> &nbsp;·&nbsp; ⚡ <b>{tps:.1f} t/s</b> &nbsp;·&nbsp; 🔢 <b>{tot_tokens} token</b>"
                        f"</div>"
                    )

                    if not full_thinking:
                        thinking_container.empty()

                    # Rimuovi il cursore ▌ e mostra il testo finale con metriche
                    clean_display = re.sub(r"\n*<div style=.*?⏱️.*?</div>\s*", "", raw_accumulated_response, flags=re.DOTALL).strip()
                    if response_placeholder and clean_display:
                        response_placeholder.markdown(clean_display + metrics_footer, unsafe_allow_html=True)

            # 5. Post-elaborazione: estrazione memorie e salvataggio nel database
            if raw_accumulated_response or full_thinking:
                clean_final, new_memories = chatbot.extract_and_save_memories(
                    conn, email_attiva, raw_accumulated_response
                )

                # Salva risposta dell'assistente nel DB con metriche (garantendo un solo footer)
                clean_final = re.sub(r"\n*<div style=.*?⏱️.*?</div>\s*", "", clean_final, flags=re.DOTALL).strip()
                saved_content = clean_final + metrics_footer
                chatbot.save_chat_message(
                    conn, email_attiva, "assistant", saved_content, full_thinking
                )

                # Notifica all'utente se sono state apprese nuove memorie
                if new_memories:
                    badges = [f"[{m['categoria']}] {m['chiave']}: {m['valore']}" for m in new_memories]
                    st.toast(f"🧠 Nuova memoria appresa: {', '.join(badges)}", icon="🧠")

                # Rerun per consolidare la cronologia pulita
                st.rerun()

    # Azioni di gestione chat
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    c_btn1, c_btn2, _ = st.columns([1, 1, 2])
    with c_btn1:
        if st.button("🗑️ Cancella Cronologia Chat", help="Elimina tutti i messaggi per questo utente"):
            chatbot.clear_chat_history(conn, email_attiva)
            st.success("Cronologia chat cancellata.")
            st.rerun()
    with c_btn2:
        if cronologia:
            # Esportazione chat in formato markdown
            testo_export = f"# Conversazione con Chatbot - {ctx['nome']} ({email_attiva})\n"
            testo_export += f"Data esportazione: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            for m in cronologia:
                testo_export += f"### {m['role'].upper()} ({m['creato_il']}):\n{m['content']}\n\n"
            st.download_button(
                "📥 Esporta Chat (MD)",
                data=testo_export,
                file_name=f"chat_{email_attiva.replace('@', '_')}.md",
                mime="text/markdown",
            )

# ===========================================================================
# TAB 2: AGENDA PERSONALE (FUNCTION CALLING)
# ===========================================================================
with tab_agenda:
    st.markdown(f"#### 📅 Agenda Personale di {ctx['nome']}")
    st.caption(
        "Gli impegni e le riunioni possono essere pianificati conversando direttamente con l'assistente "
        "(tramite Function Calling automatico) oppure gestiti e consultati da questo pannello."
    )

    with st.expander("📆 Vista Calendario Giornaliero e Fasce Orarie (Frazioni di Tempo)", expanded=False):
        c_cal_date, c_cal_dur = st.columns([1.5, 1.5])
        with c_cal_date:
            giorno_ispezione = st.date_input("Seleziona data da ispezionare", value=datetime.now().date() + pd.Timedelta(days=1), key=f"date_disp_{email_attiva}")
        with c_cal_dur:
            dur_filter = st.selectbox("Filtro durata minima slot", options=[0, 15, 30, 45, 60], format_func=lambda x: "Tutti gli slot liberi" if x == 0 else f"Almeno {x} minuti", key=f"dur_disp_{email_attiva}")

        disp_res = agenda.calcola_disponibilita_giorno(conn, email_attiva, str(giorno_ispezione), durata_minuti_richiesta=dur_filter)
        md_cal = agenda.format_daily_calendar_markdown(disp_res)
        st.markdown(md_cal)

    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    col_ag_l, col_ag_r = st.columns([1.5, 1.0])

    with col_ag_l:
        st.markdown("##### 📋 Impegni e Appuntamenti")

        filtro_stato = st.radio(
            "Filtro visualizzazione agenda",
            options=["Tutti", "Solo Da Completare", "Completati"],
            horizontal=True,
            label_visibility="collapsed",
            key=f"filtro_agenda_{email_attiva}",
        )

        eventi_vista = agenda.get_eventi_utente(conn, email_attiva)
        if filtro_stato == "Solo Da Completare":
            eventi_vista = [e for e in eventi_vista if not e["completato"]]
        elif filtro_stato == "Completati":
            eventi_vista = [e for e in eventi_vista if e["completato"]]

        if not eventi_vista:
            st.info("Nessun impegno in agenda per questo utente. Chiedi all'assistente in chat di fissarne uno oppure aggiungilo qui a destra!")
        else:
            cat_icons = {
                "riunione": "👥",
                "promemoria": "🔔",
                "scadenza": "⏳",
                "chiamata": "📞",
                "personale": "👤",
                "impegno": "📌",
            }

            for ev in eventi_vista:
                icon = cat_icons.get(ev["categoria"], "📌")
                status_badge = "✅ Completato" if ev["completato"] else "⏳ In programma"

                with st.container():
                    c_info, c_action = st.columns([4.2, 1.8])
                    with c_info:
                        dettagli = []
                        if ev["data_fine"]:
                            dettagli.append(f"Fine: `{ev['data_fine']}`")
                        if ev["luogo"]:
                            dettagli.append(f"📍 {ev['luogo']}")
                        str_dettagli = " · ".join(dettagli)
                        if str_dettagli:
                            str_dettagli = f" ({str_dettagli})"

                        st.markdown(
                            f"{icon} **{ev['titolo']}** — `<small style='color: #64748B;'>{status_badge} [{ev['categoria'].upper()}]</small>`  \n"
                            f"🗓️ **{ev['data_inizio']}**{str_dettagli}"
                            + (f"  \n📝 *{ev['note']}*" if ev["note"] else ""),
                            unsafe_allow_html=True,
                        )
                    with c_action:
                        cb1, cb2 = st.columns(2)
                        with cb1:
                            btn_ico = "↩️" if ev["completato"] else "✔️"
                            tooltip = "Riapri impegno" if ev["completato"] else "Segna come completato"
                            if st.button(btn_ico, key=f"tgl_ev_{ev['id']}", help=tooltip):
                                agenda.segna_completato(conn, email_attiva, ev["id"], completato=not ev["completato"])
                                st.rerun()
                        with cb2:
                            if st.button("🗑️", key=f"del_ev_{ev['id']}", help="Elimina impegno"):
                                agenda.elimina_evento(conn, email_attiva, ev["id"])
                                st.rerun()
                    st.markdown("<hr style='margin: 4px 0 10px 0;'>", unsafe_allow_html=True)

    with col_ag_r:
        st.markdown("##### ➕ Nuovo Impegno Manuale")
        with st.form(f"form_nuovo_evento_{email_attiva}"):
            nuovo_titolo = st.text_input("Titolo / Oggetto *", placeholder="es. Riunione con fornitore")
            c_d1, c_d2 = st.columns(2)
            now_dt = datetime.now()
            with c_d1:
                data_in = st.date_input("Data Inizio *", value=now_dt.date())
                ora_in = st.time_input("Ora Inizio *", value=now_dt.time().replace(second=0, microsecond=0))
            with c_d2:
                ha_fine = st.checkbox("Specifica Fine", value=True)
                ora_fine = st.time_input("Ora Fine", value=(now_dt + pd.Timedelta(hours=1)).time().replace(second=0, microsecond=0), disabled=not ha_fine)

            nuova_cat = st.selectbox(
                "Categoria",
                options=["impegno", "riunione", "chiamata", "scadenza", "promemoria", "personale"],
            )
            nuovo_luogo = st.text_input("Luogo / Canale", placeholder="es. Ufficio Milano, Google Meet, Tel...")
            nuove_note = st.text_area("Note aggiuntive", placeholder="Note o partecipanti...")

            btn_salva = st.form_submit_button("Aggiungi all'Agenda", use_container_width=True)

            if btn_salva:
                if not nuovo_titolo.strip():
                    st.warning("Il titolo dell'impegno è obbligatorio.")
                else:
                    str_data_inizio = f"{data_in.strftime('%Y-%m-%d')} {ora_in.strftime('%H:%M')}"
                    str_data_fine = f"{data_in.strftime('%Y-%m-%d')} {ora_fine.strftime('%H:%M')}" if ha_fine else None
                    res = agenda.crea_evento(
                        conn,
                        email_attiva,
                        nuovo_titolo,
                        str_data_inizio,
                        data_fine=str_data_fine,
                        luogo=nuovo_luogo,
                        categoria=nuova_cat,
                        note=nuove_note,
                    )
                    if res.get("success"):
                        st.success(res.get("messaggio", "Impegno creato!"))
                        st.rerun()
                    else:
                        st.error(res.get("error", "Errore durante la creazione."))

# ===========================================================================
# TAB 3: MEMORIA & PREFERENZE APPRESE
# ===========================================================================
with tab_memoria:
    st.markdown(f"#### 🧠 Memoria Persistente di {ctx['nome']}")
    st.caption(
        "Tutto ciò che il chatbot impara conversando con l'utente viene archiviato qui "
        "e iniettato automaticamente nel system prompt per personalizzare ogni futura risposta."
    )

    col_mem_l, col_mem_r = st.columns([1.4, 1.0])

    with col_mem_l:
        st.markdown("##### Informazioni Apprese")
        memorie_utente = chatbot.get_user_memorie(conn, email_attiva)

        if not memorie_utente:
            st.info("Nessuna memoria appresa al momento. Conversa con il chatbot o aggiungi una preferenza manuale.")
        else:
            df_mem = pd.DataFrame(memorie_utente)
            # Mostra tabella delle memorie con badge di categoria
            for m in memorie_utente:
                c_icon = {
                    "orario": "⏰",
                    "preferenza": "⭐",
                    "lavoro": "💼",
                    "fatto_personale": "👤",
                    "nota": "📝",
                }.get(m["categoria"], "📌")

                with st.container():
                    c_txt, c_del = st.columns([5, 1])
                    with c_txt:
                        st.markdown(
                            f"{c_icon} **[{m['categoria'].upper()}]** `{m['chiave']}`: {m['valore']}  \n"
                            f"<small style='color: #64748B;'>Appreso il: {m['appreso_il']} · Aggiornato: {m['aggiornato_il']}</small>",
                            unsafe_allow_html=True,
                        )
                    with c_del:
                        if st.button("🗑️", key=f"del_mem_{m['id']}", help="Elimina questa memoria"):
                            chatbot.delete_memoria(conn, m["id"])
                            st.rerun()
                    st.markdown("<hr style='margin: 4px 0 10px 0;'>", unsafe_allow_html=True)

            if st.button("⚠️ Cancella Tutta la Memoria dell'Utente", type="secondary"):
                chatbot.clear_user_memorie(conn, email_attiva)
                st.success("Tutte le memorie sono state eliminate.")
                st.rerun()

    with col_mem_r:
        st.markdown("##### ➕ Aggiungi Memoria Manuale")
        with st.form("form_nuova_memoria"):
            nuova_cat = st.selectbox(
                "Categoria",
                options=["preferenza", "orario", "lavoro", "fatto_personale", "nota"],
                help="Tipo di informazione da registrare nella memoria a lungo termine",
            )
            nuova_chiave = st.text_input(
                "Chiave / Oggetto",
                placeholder="es. Pausa caffè preferita, Canale di competenza...",
            )
            nuovo_valore = st.text_area(
                "Valore / Dettaglio",
                placeholder="es. Ore 10:30 con caffè espresso ristretto",
            )
            btn_add_mem = st.form_submit_button("Salva nella Memoria", use_container_width=True)

            if btn_add_mem:
                if nuova_chiave.strip() and nuovo_valore.strip():
                    chatbot.save_memoria(conn, email_attiva, nuova_cat, nuova_chiave, nuovo_valore)
                    st.success(f"Memoria '{nuova_chiave}' registrata!")
                    st.rerun()
                else:
                    st.warning("Compila sia la chiave che il valore.")

# ===========================================================================
# TAB 3: SYSTEM PROMPT & DEBUG LLM
# ===========================================================================
with tab_debug:
    st.markdown("#### 🔍 Ispezione System Prompt & Parametri")
    st.caption("Visualizza l'esatto prompt di sistema iniettato nel modello con tutte le variabili dell'utente attivo.")

    prompt_generato = chatbot.build_system_prompt(conn, email_attiva)

    st.text_area(
        "System Prompt Completo Inviato a llama.cpp",
        value=prompt_generato,
        height=320,
        disabled=True,
    )

    # Dati grezzi utente (JSON)
    with st.expander("📄 Dati Grezzi Contesto Utente (JSON)", expanded=False):
        st.json(ctx)

    st.markdown("---")
    st.markdown("##### ⚖️ Diagnostica Modello Decisionale (Porta 8017)")
    is_dec_chk, dec_mod_name, _ = chatbot.check_decision_server(decision_url)
    c_dec1, c_dec2 = st.columns(2)
    with c_dec1:
        st.markdown(f"**Endpoint Decisionale:** `{decision_url}`")
        st.markdown(f"**Modello:** `{dec_mod_name if is_dec_chk else 'Non disponibile'}`")
    with c_dec2:
        st.markdown(f"**Stato Connessione:** {'🟢 Connesso' if is_dec_chk else '🔴 Non raggiungibile'}")
        st.markdown(f"**Classificazione automatica:** {'Attiva' if usa_decisionale else 'Disattivata'}")

    last_dec = st.session_state.get("last_decision")
    if last_dec:
        with st.expander("📊 Ultima Decisione Thinking Mode", expanded=True):
            st.json(last_dec)
