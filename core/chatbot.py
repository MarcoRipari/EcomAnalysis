"""Modulo Core per il Chatbot con LLM locale (llama.cpp) e gestione memoria utente.

Caratteristiche principali:
- Connessione a server llama.cpp locale (default: 127.0.0.1:8082).
- Gestione conversazioni isolate per utente (tabella `chatbot_messaggi`).
- Memoria a lungo termine per utente (tabella `chatbot_memoria`).
- Profilazione automatica dell'utente: orari di lavoro contrattuali, anagrafica,
  ruolo RBAC, ferie godute/residue e preferenze applicative.
- Iniezione dinamica del profilo utente e delle memorie apprese nel system prompt.
- Apprendimento automatico durante la chat (parsing tag <memoria>...</memoria>).
- Separazione trasparente del ragionamento (tag <think>...</think> di Qwen3).
- Streaming in tempo reale compatibile con Streamlit.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Generator

import pandas as pd
import requests

from core import agenda, assistant_tools, ferie, roles, site_knowledge

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8082
DEFAULT_BASE_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
DEFAULT_MODEL = "Qwen3.5-4B-XpressAI-UD.Q4_K_XL.gguf"

DEFAULT_DECISION_HOST = "127.0.0.1"
DEFAULT_DECISION_PORT = 8017
DEFAULT_DECISION_URL = f"http://{DEFAULT_DECISION_HOST}:{DEFAULT_DECISION_PORT}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Inizializzazione tabelle Database
# ---------------------------------------------------------------------------
def init_chatbot_tables(conn: sqlite3.Connection) -> None:
    """Crea le tabelle necessarie per la chat, la memoria e l'agenda degli utenti."""
    agenda.init_agenda_tables(conn)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS chatbot_messaggi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        reasoning TEXT DEFAULT '',
        creato_il TEXT NOT NULL
    );
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_chatbot_messaggi_user
    ON chatbot_messaggi(user_email, id);
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS chatbot_memoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        categoria TEXT NOT NULL DEFAULT 'preferenza',
        chiave TEXT NOT NULL,
        valore TEXT NOT NULL,
        appreso_il TEXT NOT NULL,
        aggiornato_il TEXT NOT NULL,
        UNIQUE(user_email, chiave)
    );
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_chatbot_memoria_user
    ON chatbot_memoria(user_email, categoria);
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS utenti_preferenze (
        email TEXT PRIMARY KEY,
        preferenze_json TEXT NOT NULL,
        aggiornato_il TEXT NOT NULL
    );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Gestione Cronologia Messaggi Chat
# ---------------------------------------------------------------------------
def get_chat_history(
    conn: sqlite3.Connection,
    user_email: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Restituisce la cronologia messaggi per un utente specifico ordinata cronologicamente."""
    email = (user_email or "").strip().lower()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, role, content, reasoning, creato_il
        FROM chatbot_messaggi
        WHERE LOWER(user_email) = ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (email, limit),
    ).fetchall()

    return [
        {
            "id": r[0],
            "role": r[1],
            "content": r[2],
            "reasoning": r[3] or "",
            "creato_il": r[4],
        }
        for r in rows
    ]


def save_chat_message(
    conn: sqlite3.Connection,
    user_email: str,
    role: str,
    content: str,
    reasoning: str = "",
) -> int:
    """Salva un singolo messaggio nella cronologia della chat dell'utente."""
    email = (user_email or "").strip().lower()
    now = _now_iso()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO chatbot_messaggi (user_email, role, content, reasoning, creato_il)
        VALUES (?, ?, ?, ?, ?)
        """,
        (email, role, content, reasoning, now),
    )
    conn.commit()
    return cur.lastrowid or 0


def clear_chat_history(conn: sqlite3.Connection, user_email: str) -> None:
    """Elimina tutti i messaggi per l'utente selezionato."""
    email = (user_email or "").strip().lower()
    conn.execute(
        "DELETE FROM chatbot_messaggi WHERE LOWER(user_email) = ?",
        (email,),
    )
    conn.commit()


def compact_chat_history(
    history: list[dict[str, Any]],
    max_messages: int = 4,
    max_assistant_chars: int = 300,
) -> list[dict[str, str]]:
    """Compatta la cronologia per l'invio all'LLM in modo deterministico e ultra-rapido (< 0.01ms).

    - Mantiene solo gli ultimi `max_messages` (default 4, corrispondenti a 2 turni completi).
    - Rimuove footer HTML di metriche (es. tempi o div tecnici).
    - Rimuove righe di tabelle markdown ingombranti per non saturare la finestra di contesto.
    - Tronca risposte discorsive molto lunghe dell'assistente a `max_assistant_chars`.
    """
    if not history:
        return []

    recent = history[-max_messages:] if len(history) > max_messages else history
    compacted: list[dict[str, str]] = []

    for m in recent:
        role = m.get("role", "user")
        txt = str(m.get("content", "") or "")

        # Rimuove footer HTML metriche o badge di rendering
        txt = re.sub(r"\n*<div style=.*?⏱️.*?</div>\s*", "", txt, flags=re.DOTALL).strip()

        if role == "assistant":
            # Se conteneva tabelle markdown, mantiene le righe descrittive ed esclude le griglie tabellari
            if "|" in txt and "---" in txt:
                lines = [l for l in txt.splitlines() if not l.strip().startswith("|")]
                txt = "\n".join(lines).strip()
            if len(txt) > max_assistant_chars:
                txt = txt[:max_assistant_chars] + "..."

        compacted.append({"role": role, "content": txt})

    return compacted


# ---------------------------------------------------------------------------
# Gestione Memoria Permanente Utente
# ---------------------------------------------------------------------------
def get_user_memorie(
    conn: sqlite3.Connection,
    user_email: str,
) -> list[dict[str, Any]]:
    """Restituisce l'elenco delle memorie e preferenze apprese per l'utente."""
    email = (user_email or "").strip().lower()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, categoria, chiave, valore, appreso_il, aggiornato_il
        FROM chatbot_memoria
        WHERE LOWER(user_email) = ?
        ORDER BY categoria ASC, chiave ASC
        """,
        (email,),
    ).fetchall()

    return [
        {
            "id": r[0],
            "categoria": r[1],
            "chiave": r[2],
            "valore": r[3],
            "appreso_il": r[4],
            "aggiornato_il": r[5],
        }
        for r in rows
    ]


def save_memoria(
    conn: sqlite3.Connection,
    user_email: str,
    categoria: str,
    chiave: str,
    valore: str,
) -> bool:
    """Aggiunge o aggiorna una memoria persistente per l'utente."""
    email = (user_email or "").strip().lower()
    cat_clean = (categoria or "preferenza").strip().lower()
    k_clean = (chiave or "").strip()
    v_clean = (valore or "").strip()

    if not email or not k_clean or not v_clean:
        return False

    now = _now_iso()
    conn.execute(
        """
        INSERT INTO chatbot_memoria (user_email, categoria, chiave, valore, appreso_il, aggiornato_il)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_email, chiave) DO UPDATE SET
            categoria = excluded.categoria,
            valore = excluded.valore,
            aggiornato_il = excluded.aggiornato_il
        """,
        (email, cat_clean, k_clean, v_clean, now, now),
    )
    conn.commit()
    return True


def delete_memoria(conn: sqlite3.Connection, memoria_id: int) -> bool:
    """Elimina una specifica memoria per ID."""
    cur = conn.cursor()
    cur.execute("DELETE FROM chatbot_memoria WHERE id = ?", (memoria_id,))
    conn.commit()
    return cur.rowcount > 0


def clear_user_memorie(conn: sqlite3.Connection, user_email: str) -> None:
    """Elimina tutte le memorie apprese per l'utente."""
    email = (user_email or "").strip().lower()
    conn.execute(
        "DELETE FROM chatbot_memoria WHERE LOWER(user_email) = ?",
        (email,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Profilazione Utente & Contesto Completo
# ---------------------------------------------------------------------------
def get_user_context(conn: sqlite3.Connection, user_email: str) -> dict[str, Any]:
    """Raccoglie l'identità, orari, ferie, ruolo e memorie dell'utente."""
    email_clean = (user_email or "").strip().lower()
    nome_presunto = ferie.nome_da_email(email_clean)

    # Ruolo RBAC
    ruolo = roles.get_user_role(conn, email_clean)

    # Anagrafica e orari contrattuali da dipendenti
    dip_info: dict[str, Any] = {}
    df_dip = ferie.get_dipendenti(conn, solo_attivi=False)
    if not df_dip.empty:
        match_email = df_dip[df_dip["email"].str.lower() == email_clean]
        if not match_email.empty:
            dip_info = match_email.iloc[0].to_dict()
        else:
            match_nome = df_dip[df_dip["nome"].str.lower() == nome_presunto.lower()]
            if not match_nome.empty:
                dip_info = match_nome.iloc[0].to_dict()

    nome_visualizzato = dip_info.get("nome") or nome_presunto

    # Orari contrattuali
    mattina_inizio = dip_info.get("mattina_inizio", "08:00")
    mattina_fine = dip_info.get("mattina_fine", "12:00")
    pomeriggio_inizio = dip_info.get("pomeriggio_inizio", "14:00")
    pomeriggio_fine = dip_info.get("pomeriggio_fine", "18:00")
    totale_ferie = float(dip_info.get("totale_annuo", ferie.DEFAULT_BUDGET_ANNUO))

    # Ferie e permessi anno corrente
    anno_corrente = datetime.now().year
    giorni_goduti = 0.0
    giorni_disponibili = totale_ferie
    giorni_residui = totale_ferie
    permessi_ore = 0.0
    if dip_info:
        try:
            df_storico = ferie.get_ferie_storico(conn)
            riepilogo_anni = ferie.calcola_riepilogo_ferie_annuale(
                df_storico, nome_visualizzato, totale_ferie
            )
            info_anno = riepilogo_anni.get(anno_corrente, {})
            giorni_goduti = float(info_anno.get("usati", 0.0))
            giorni_disponibili = float(info_anno.get("disponibili", totale_ferie))
            giorni_residui = float(info_anno.get("residuo", totale_ferie))

            # Calcolo specifico permessi orari anno corrente
            if not df_storico.empty and "nome" in df_storico.columns:
                perm_dip = df_storico[
                    (df_storico["nome"].str.lower() == nome_visualizzato.lower()) &
                    (df_storico["tipo"] == "Permesso Orario")
                ]
                for _, r in perm_dip.iterrows():
                    try:
                        d_ini = pd.to_datetime(r["data_inizio"]).date()
                        if d_ini.year == anno_corrente:
                            permessi_ore += float(r.get("giorni_lavorativi", 0.0) or 0.0) * 8.0
                    except Exception:
                        pass
        except Exception:
            pass

    # Preferenze salvate in utenti_preferenze (es. UI, widget)
    pref_ui: dict[str, Any] = {}
    try:
        cur = conn.cursor()
        row_pref = cur.execute(
            "SELECT preferenze_json FROM utenti_preferenze WHERE LOWER(email) = ?",
            (email_clean,),
        ).fetchone()
        if row_pref and row_pref[0]:
            pref_ui = json.loads(row_pref[0])
    except Exception:
        pref_ui = {}

    # Memorie apprese
    memorie = get_user_memorie(conn, email_clean)

    return {
        "email": email_clean,
        "nome": nome_visualizzato,
        "ruolo": ruolo,
        "ha_anagrafica_dipendente": bool(dip_info),
        "orari": {
            "mattina_inizio": mattina_inizio,
            "mattina_fine": mattina_fine,
            "pomeriggio_inizio": pomeriggio_inizio,
            "pomeriggio_fine": pomeriggio_fine,
            "fascia_mattina": f"{mattina_inizio} - {mattina_fine}",
            "fascia_pomeriggio": f"{pomeriggio_inizio} - {pomeriggio_fine}",
        },
        "ferie": {
            "anno": anno_corrente,
            "totale_annuo": totale_ferie,
            "disponibili": giorni_disponibili,
            "godute": round(giorni_goduti, 2),
            "permessi_ore": round(permessi_ore, 2),
            "residue": round(giorni_residui, 2),
        },
        "preferenze_ui": pref_ui,
        "memorie": memorie,
    }


def build_system_prompt(
    conn: sqlite3.Connection,
    user_email: str,
    additional_notes: str = "",
) -> str:
    """Costruisce il system prompt personalizzato completo per l'utente."""
    ctx = get_user_context(conn, user_email)
    orari = ctx["orari"]
    ferie_info = ctx["ferie"]
    memorie = ctx["memorie"]

    data_ora_corrente = datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt_lines = [
        "Sei l'assistente operativo aziendale di EcomAnalysis.",
        "Priorità assoluta: MASSIMA VELOCITÀ, PRECISIONE ED ESSENZIALITÀ OPERATIVA.",
        "",
        "### REGOLE OPERATIVE - ZERO CHIACCHIERE (TASSATIVO):",
        "1. ZERO CONVENEVOLI E SALUTI: NON salutare ('Ciao Marco', 'Buongiorno'), NON usare convenevoli o formule introduttive ('Certamente', 'Ecco i dati', 'Posso confermarti che...').",
        "2. ZERO FRASI DI CHIUSURA: NON inserire MAI formule o offerte finali ('Posso aiutarti con altro?', 'Dimmi se vuoi fissare la riunione', 'Resto a disposizione per...').",
        "3. RISPOSTE ULTRA-CONCISE: Vai dritto al punto con dati numerici, elenchi puntati o tabelle compatti. Se è richiesta una risposta discorsiva, limitati a 1-2 frasi essenziali.",
        "4. STRUMENTI OPERATIVI AZIENDALI (TOOLS): Hai a disposizione una suite di strumenti integrati:",
        "   - AGENDA & RIUNIONI: per impegni personali (agenda_inserisci_impegno, agenda_visualizza_impegni, agenda_trova_slot_liberi) e per incontri con colleghi o interi reparti (usa 'agenda_trova_slot_condiviso' quando chiedono di trovare un buco insieme a una persona come 'Giampiero Mattei' o con 'la logistica').",
        "   - HR & FERIE: per verificare disponibilità o sovrapposizioni ferie per un periodo o reparto (usa 'ferie_verifica_sovrapposizioni') e consultare il monte ferie (usa 'ferie_consulta_saldo'). Ricorda sempre che le ferie si concordano a voce con il responsabile e che non esistono ROL distinti (tutto 'ferie'). Se l'utente è Admin e chiede di registrare un'assenza già concordata, usa 'ferie_registra_assenza'.",
        "   - FAST ANALYTICS & DATI: per query veloci su fatturato, vendite, paia, resi o top canali, usa 'analytics_kpi_rapido' per fornire numeri aggregati istantanei.",
        "   - TRACKING SPEDIZIONI: se l'utente fornisce un codice di spedizione (es. GLS, DHL, UPS, BRT, Poste), usa 'tracking_spedizione' per generare il link ufficiale di monitoraggio.",
        "   REGOLA CRITICA AZIONI: Quando l'utente ti chiede di fissare, confermare, registrare o verificare un impegno, un'assenza, un KPI o un tracking, DEVI SEMPRE invocare il rispettivo tool tramite function calling. Inizia IMMEDIATAMENTE con la chiamata al tool senza emettere alcun testo prima né dopo (NON scrivere MAI frasi come 'Certamente, procedo a...'). NON limitarti MAI a rispondere con solo testo affermativo senza invocare il tool.",
        "5. DOMANDE SU ORARI/FERIE: Fai sempre riferimento ai dati contrattuali e al saldo reale dell'utente. Ricorda: ferie sempre a voce con il responsabile, no ROL distinti.",
        "6. LINGUA DI RAGIONAMENTO: Se utilizzi una thinking mode, pensa e ragiona SEMPRE in italiano nei tag <think>...</think>.",
        "7. APPRENDIMENTO ATTIVO E MEMORIA: Memorizza ESCLUSIVAMENTE preferenze personali stabili e abitudini comunicative dell'utente (es. canale preferito Meet/Teams, stile di risposta, orari fissi di preferenza). NON memorizzare MAI saluti, appuntamenti, riunioni, promemoria o impegni temporanei (questi appartengono esclusivamente all'agenda e non alla memoria). Se e solo se l'utente esprime una preferenza permanente, confermagliela in modo telegrafico e aggiungi alla FINE della risposta il blocco:",
        "<memoria>",
        "- [categoria] Chiave: Valore",
        "</memoria>",
        "dove la categoria deve essere una tra: preferenza, orario, lavoro, fatto_personale, nota.",
        "",
        site_knowledge.get_site_knowledge_prompt_snippet(),
        "",
        "### Identità e Profilo dell'Utente:",
        f"- Nome: {ctx['nome']}",
        f"- Email: {ctx['email']}",
        f"- Ruolo in azienda: {ctx['ruolo']}",
        f"- Orario contrattuale di lavoro: Mattina {orari['fascia_mattina']}, Pomeriggio {orari['fascia_pomeriggio']}",
        f"- Saldo ferie {ferie_info['anno']}: {ferie_info['residue']:.2f} giorni residui su {ferie_info['disponibili']:.1f} disponibili (Budget annuo: {ferie_info['totale_annuo']:.1f} gg, Giorni usati/goduti: {ferie_info['godute']:.2f} gg, Permessi orari usati: {ferie_info['permessi_ore']:.1f} ore)",
    ]

    if memorie:
        prompt_lines.append("")
        prompt_lines.append("### Memorie, Abitudini e Preferenze Apprese su questo Utente:")
        for m in memorie:
            cat = m["categoria"].upper()
            prompt_lines.append(f"- [{cat}] {m['chiave']}: {m['valore']}")
    else:
        prompt_lines.append("")
        prompt_lines.append("### Memorie Apprese:")
        prompt_lines.append("- Nessuna preferenza o fatto personale ancora registrato.")

    if additional_notes:
        prompt_lines.append("")
        prompt_lines.append("### Note Aggiuntive:")
        prompt_lines.append(additional_notes.strip())

    prompt_lines.extend([
        "",
        f"[Riferimento temporale del sistema: {data_ora_corrente}]",
    ])

    return "\n".join(prompt_lines)


# ---------------------------------------------------------------------------
# Parsing Ragionamento (<think>) e Memorie (<memoria>)
# ---------------------------------------------------------------------------
def parse_reasoning_and_content(raw_text: str) -> tuple[str, str]:
    """Separa il blocco di ragionamento <think>...</think> dal corpo del messaggio."""
    if not raw_text:
        return "", ""

    # Se c'è un blocco completo <think>...</think>
    match = re.search(r"<think>(.*?)</think>", raw_text, re.DOTALL)
    if match:
        reasoning = match.group(1).strip()
        content = raw_text[: match.start()] + raw_text[match.end() :]
        return reasoning, content.strip()

    # Se c'è un <think> non chiuso (es. streaming interrotto)
    if "<think>" in raw_text:
        parts = raw_text.split("<think>", 1)
        return parts[1].strip(), parts[0].strip()

    return "", raw_text.strip()


def extract_and_save_memories(
    conn: sqlite3.Connection,
    user_email: str,
    text: str,
) -> tuple[str, list[dict[str, str]]]:
    """Individua i tag <memoria>...</memoria>, salva le memorie nel DB e restituisce il testo pulito."""
    if not text:
        return "", []

    memories_found: list[dict[str, str]] = []

    # Regex per catturare <memoria>...</memoria> o <memory>...</memory>
    pattern = re.compile(r"<(?:memoria|memory)>(.*?)</(?:memoria|memory)>", re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(text)

    for block in matches:
        lines = block.strip().splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("```"):
                continue

            # Rimuove elenchi puntati o asterischi
            line_clean = re.sub(r"^[-*•\d\.]+\s*", "", line_str).strip()

            # Estrae categoria [categoria] o **categoria**
            cat = "preferenza"
            cat_match = re.search(r"^[\[\*]+([a-zA-Z_\s]+)[\]\*]+\s*", line_clean)
            if cat_match:
                extracted_cat = cat_match.group(1).strip().lower()
                if extracted_cat in {"orario", "preferenza", "lavoro", "fatto_personale", "nota"}:
                    cat = extracted_cat
                elif "orari" in extracted_cat:
                    cat = "orario"
                line_clean = line_clean[cat_match.end() :].strip()

            # Rimuove eventuale prefisso "Chiave:" o "Key:"
            line_clean = re.sub(r"^(?:chiave|key):\s*", "", line_clean, flags=re.IGNORECASE)

            # Separa Chiave: Valore
            if ":" in line_clean:
                k, v = line_clean.split(":", 1)
                k = k.strip().strip("*_[]")
                v = v.strip().strip("*_[]")

                # FILTRO ANTI-MEMORIE SPURIE: Rifiuta saluti, appuntamenti ed elementi dell'agenda
                k_lower = k.lower()
                v_lower = v.lower()
                blacklist = (
                    "saluto", "saluti", "ciao", "buongiorno", "buonasera",
                    "riunion", "impegn", "agenda", "calendario", "appuntament",
                    "oggi", "domani", "ieri", "ferie", "cancell", "elimin",
                    "nessuna", "nessun", "fissa"
                )
                if any(b in k_lower or b in v_lower for b in blacklist):
                    continue

                if k and v:
                    # Salva nel database
                    saved = save_memoria(conn, user_email, cat, k, v)
                    if saved:
                        memories_found.append({"categoria": cat, "chiave": k, "valore": v})

    # Rimuove il blocco <memoria> dal testo mostrato all'utente
    clean_text = pattern.sub("", text).strip()
    return clean_text, memories_found


# ---------------------------------------------------------------------------
# Client LLM Server llama.cpp
# ---------------------------------------------------------------------------
def check_llm_server(
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[bool, str, list[str], str]:
    """Verifica lo stato del server llama.cpp e recupera i modelli caricati."""
    base = base_url.rstrip("/")
    models_list: list[str] = []
    active_model = ""

    # 1. Prova /health
    try:
        r_health = requests.get(f"{base}/health", timeout=2.5)
        is_healthy = r_health.status_code == 200
    except Exception as exc:
        return False, "", [], f"Connessione fallita a {base}: {exc}"

    # 2. Prova /v1/models
    try:
        r_models = requests.get(f"{base}/v1/models", timeout=3.0)
        if r_models.status_code == 200:
            data = r_models.json()
            items = data.get("data", []) or data.get("models", [])
            for it in items:
                m_id = it.get("id") or it.get("name") or it.get("model")
                if m_id:
                    models_list.append(m_id)
            if models_list:
                active_model = models_list[0]
    except Exception:
        pass

    if not active_model:
        active_model = DEFAULT_MODEL

    return is_healthy, active_model, models_list, ""


def stream_chat_response(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1500,
    enable_thinking: bool | None = False,
    metrics: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Generator[str, None, None]:
    """Esegue una chiamata in streaming verso /v1/chat/completions di llama.cpp."""
    if enable_thinking is None:
        if "prompt_requires_think" in kwargs:
            enable_thinking = kwargs["prompt_requires_think"]
        else:
            enable_thinking = False

    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if enable_thinking is not None:
        payload["chat_template_kwargs"] = {"enable_thinking": bool(enable_thinking)}
        payload["extra_body"] = {"enable_thinking": bool(enable_thinking)}

    resp = requests.post(
        endpoint,
        json=payload,
        stream=True,
        timeout=180,
    )
    resp.raise_for_status()

    # Assicura codifica corretta UTF-8 per lo streaming SSE
    resp.encoding = "utf-8"
    in_reasoning_mode = False

    for raw_line in resp.iter_lines():
        if not raw_line:
            continue
        if isinstance(raw_line, bytes):
            line_str = raw_line.decode("utf-8", errors="replace").strip()
        else:
            line_str = str(raw_line).strip()

        if not line_str.startswith("data:"):
            continue

        raw_data = line_str[len("data:") :].strip()
        if raw_data == "[DONE]":
            break

        try:
            chunk = json.loads(raw_data)
            timings = chunk.get("timings")
            if timings and metrics is not None:
                metrics.update(timings)

            choices = chunk.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            reasoning_part = delta.get("reasoning_content") or delta.get("reasoning")
            content_part = delta.get("content")

            # Se il server invia reasoning_content (specifica llama.cpp / DeepSeek / Qwen)
            if reasoning_part:
                if not in_reasoning_mode:
                    in_reasoning_mode = True
                    yield "<think>\n"
                yield reasoning_part

            # Quando inizia la risposta effettiva, chiudi eventuale blocco reasoning
            if content_part:
                if in_reasoning_mode:
                    in_reasoning_mode = False
                    yield "\n</think>\n"
                yield content_part

        except Exception:
            continue

    if in_reasoning_mode:
        yield "\n</think>\n"


def prompt_requires_agenda(prompt: str) -> bool:
    """Rileva se il prompt dell'utente richiede l'uso degli strumenti dell'assistente."""
    return assistant_tools.prompt_requires_tools(prompt)


def _format_fast_path_response(
    fn_name: str,
    args: dict[str, Any],
    tool_output: dict[str, Any],
) -> str | None:
    """Formatta istantaneamente una risposta chiara per azioni deterministiche dell'agenda (Fast-Path)."""
    if fn_name == "agenda_inserisci_impegno":
        if tool_output.get("success"):
            titolo = tool_output.get("titolo") or args.get("titolo", "Impegno")
            inizio = tool_output.get("data_inizio") or args.get("data_inizio", "")
            fine = tool_output.get("data_fine") or args.get("data_fine", "")
            fine_str = f" - {fine.split(' ')[-1]}" if fine else ""
            luogo = tool_output.get("luogo") or args.get("luogo", "")
            luogo_str = f"\n- **Luogo:** {luogo}" if luogo and luogo != "Da definire" else ""
            cat = tool_output.get("categoria") or args.get("categoria", "riunione")
            ev_id = tool_output.get("evento_id", "")
            id_str = f" *(ID #{ev_id})*" if ev_id else ""
            return (
                f"✅ **Impegno Registrato con Successo!**{id_str}\n\n"
                f"- **Titolo:** {titolo}\n"
                f"- **Data e Ora:** {inizio}{fine_str}\n"
                f"- **Categoria:** {cat.capitalize()}"
                f"{luogo_str}"
            )
        elif tool_output.get("conflitto"):
            return (
                f"⚠️ **Conflitto di Orario**\n\n"
                f"{tool_output.get('error')}\n\n"
                f"L'impegno non è stato inserito per evitare sovrapposizioni."
            )
        elif tool_output.get("fuori_orario"):
            return (
                f"⏳ **Orario Fuori Turno Lavorativo**\n\n"
                f"{tool_output.get('error')}\n\n"
                f"Gli impegni possono essere fissati solo durante l'orario contrattuale."
            )
        elif tool_output.get("in_ferie"):
            return (
                f"🏖️ **Assenza Registrata per Questa Data**\n\n"
                f"{tool_output.get('error')}\n\n"
                f"Non è possibile registrare appuntamenti nei giorni di ferie o assenza."
            )
        else:
            err_msg = tool_output.get("error") or "Si è verificato un errore durante l'inserimento."
            return (
                f"❌ **Impossibile registrare l'impegno**\n\n"
                f"{err_msg}"
            )

    elif fn_name in {"agenda_elimina_impegno", "agenda_elimina_tutti_giorno"}:
        if tool_output.get("success"):
            msg = tool_output.get("messaggio") or "Gli eventi sono stati rimossi dall'agenda."
            return f"🗑️ **Impegni Cancellati**\n\n{msg}"
        else:
            err_msg = tool_output.get("error") or "Impossibile eliminare gli impegni specificati."
            return f"⚠️ **Errore Eliminazione**\n\n{err_msg}"

    elif fn_name == "agenda_completa_impegno":
        if tool_output.get("success"):
            msg = tool_output.get("messaggio") or "L'evento è stato contrassegnato come completato."
            return f"✔️ **Impegno Completato**\n\n{msg}"
        else:
            err_msg = tool_output.get("error") or "Impossibile contrassegnare l'evento come completato."
            return f"⚠️ **Errore**\n\n{err_msg}"

    elif fn_name == "agenda_trova_slot_liberi":
        return agenda.format_daily_calendar_markdown(tool_output)

    elif fn_name == "agenda_visualizza_impegni":
        eventi = tool_output.get("eventi", [])
        d_da = args.get("data_da") or tool_output.get("data_da", "")
        d_str = f" ({d_da})" if d_da else ""
        if not eventi:
            return f"📅 **Agenda{d_str}:** Nessun impegno in programma."

        righe = [f"📅 **Impegni in Agenda{d_str} ({len(eventi)}):**"]
        for ev in eventi:
            ini = ev.get("data_inizio", "")
            fine = ev.get("data_fine", "")
            ora_str = ini
            if " " in ini:
                data_p, ora_ini = ini.split(" ", 1)
                ora_fine = fine.split(" ", 1)[1] if fine and " " in fine else fine
                ora_str = f"{data_p} {ora_ini[:5]} - {ora_fine[:5]}" if ora_fine else f"{data_p} {ora_ini[:5]}"
            luogo = f" · *{ev['luogo']}*" if ev.get("luogo") and ev["luogo"] != "Da definire" else ""
            note = f" · *{ev['note']}*" if ev.get("note") else ""
            righe.append(f"- 🕒 **{ora_str}**: {ev.get('titolo', 'Impegno')}{luogo}{note}")
        return "\n".join(righe)

    return None


def chat_turn_with_tools(
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    conn: sqlite3.Connection,
    user_email: str,
    temperature: float = 0.7,
    max_tokens: int = 350,
    tools: list[dict[str, Any]] | None = None,
    enable_thinking: bool | None = False,
    **kwargs: Any,
) -> Generator[tuple[str, Any], None, None]:
    """Esegue un turno di conversazione con supporto a Function Calling / Tools per l'agenda in streaming continuo.

    Genera tuple (tipo_evento, dato):
    - ('tool_call', {'name': fn_name, 'args': args_dict, 'id': call_id})
    - ('tool_result', {'name': fn_name, 'result': result_dict})
    - ('chunk', str_chunk)
    """
    last_user_prompt = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_prompt = m.get("content", "")
            break

    if tools is not None:
        tools_schema = tools
    else:
        if assistant_tools.prompt_requires_tools(last_user_prompt):
            tools_schema = assistant_tools.get_scoped_tools_schema(last_user_prompt)
        else:
            tools_schema = None


    if enable_thinking is None:
        if "prompt_requires_think" in kwargs:
            enable_thinking = kwargs["prompt_requires_think"]
        else:
            enable_thinking = False

    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"

    payload_step1: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.2 if tools_schema else temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if tools_schema:
        payload_step1["tools"] = tools_schema
    if enable_thinking is not None:
        payload_step1["chat_template_kwargs"] = {"enable_thinking": bool(enable_thinking)}
        payload_step1["extra_body"] = {"enable_thinking": bool(enable_thinking)}

    try:
        r1 = requests.post(endpoint, json=payload_step1, stream=True, timeout=120)
        r1.raise_for_status()
        r1.encoding = "utf-8"
    except Exception:
        # Fallback a streaming classico
        for chunk in stream_chat_response(
            base_url, model, messages, temperature, max_tokens, enable_thinking=enable_thinking
        ):
            yield ("chunk", chunk)
        return

    in_reasoning_mode = False
    accumulated_content: list[str] = []
    tool_calls_acc: dict[int, dict[str, str]] = {}

    for raw_line in r1.iter_lines():
        if not raw_line:
            continue
        line_str = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
        if not line_str.startswith("data:"):
            continue
        raw_data = line_str[len("data:"):].strip()
        if raw_data == "[DONE]":
            break

        try:
            chunk = json.loads(raw_data)
        except Exception:
            continue

        timings = chunk.get("timings")
        if timings:
            yield ("metrics", timings)

        choices = chunk.get("choices", [])
        if not choices:
            continue

        choice = choices[0]
        delta = choice.get("delta", {})
        reasoning_part = delta.get("reasoning_content") or delta.get("reasoning")
        content_part = delta.get("content")
        tc_deltas = delta.get("tool_calls")

        # 1. Se il modello emette ragionamento (thinking), mostralo subito in streaming
        if reasoning_part:
            if not in_reasoning_mode:
                in_reasoning_mode = True
                yield ("chunk", "<think>\n")
            yield ("chunk", reasoning_part)

        # 2. Se il modello emette contenuto testuale, mostralo subito in streaming
        if content_part:
            if in_reasoning_mode:
                in_reasoning_mode = False
                yield ("chunk", "\n</think>\n")
            yield ("chunk", content_part)
            accumulated_content.append(content_part)

        # 3. Se il modello emette chiamate a tool in streaming, accumula frammenti
        if tc_deltas:
            for tc in tc_deltas:
                idx = tc.get("index", 0)
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {
                        "id": tc.get("id", f"call_{idx}"),
                        "name": "",
                        "arguments": "",
                    }
                if tc.get("id"):
                    tool_calls_acc[idx]["id"] = tc.get("id")
                fn_delta = tc.get("function", {})
                if fn_delta.get("name"):
                    tool_calls_acc[idx]["name"] += fn_delta["name"]
                if fn_delta.get("arguments"):
                    tool_calls_acc[idx]["arguments"] += fn_delta["arguments"]

    if in_reasoning_mode:
        yield ("chunk", "\n</think>\n")

    # Se ci sono chiamate a tool
    if tool_calls_acc:
        executed_messages = list(messages)
        tools_list_payload = []
        for idx in sorted(tool_calls_acc.keys()):
            tc_data = tool_calls_acc[idx]
            tools_list_payload.append({
                "id": tc_data["id"],
                "type": "function",
                "function": {
                    "name": tc_data["name"],
                    "arguments": tc_data["arguments"],
                },
            })

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(accumulated_content) or None,
            "tool_calls": tools_list_payload,
        }
        executed_messages.append(assistant_msg)

        executed_tools_data: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

        for tc_data in tools_list_payload:
            fn_name = tc_data["function"]["name"]
            raw_args = tc_data["function"]["arguments"]
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}

            yield ("tool_call", {"name": fn_name, "args": args, "id": tc_data["id"]})

            # Esecuzione del tool in Python
            tool_output = assistant_tools.esegui_tool_assistente(
                conn, user_email, fn_name, args, user_prompt=last_user_prompt
            )
            yield ("tool_result", {"name": fn_name, "result": tool_output})

            executed_tools_data.append((fn_name, args, tool_output))

            executed_messages.append({
                "role": "tool",
                "tool_call_id": tc_data["id"],
                "content": json.dumps(tool_output, ensure_ascii=False),
            })

        # FAST-PATH: Se tutte le chiamate ai tool sono deterministiche, rispondi istantaneamente da Python
        # senza attendere il secondo passaggio dell'LLM (risparmio di ~8-18 secondi ed eliminazione allucinazioni)
        fast_path_candidates = {
            "agenda_inserisci_impegno",
            "agenda_visualizza_impegni",
            "agenda_elimina_impegno",
            "agenda_elimina_tutti_giorno",
            "agenda_completa_impegno",
            "agenda_trova_slot_liberi",
            "agenda_trova_slot_condiviso",
            "ferie_verifica_sovrapposizioni",
            "ferie_consulta_saldo",
            "ferie_registra_assenza",
            "analytics_kpi_rapido",
            "tracking_spedizione",
        }
        all_candidates = bool(executed_tools_data) and all(item[0] in fast_path_candidates for item in executed_tools_data)
        if all_candidates:
            fast_resps = []
            for item_fn, item_args, item_out in executed_tools_data:
                resp = assistant_tools.format_fast_path_response(item_fn, item_args, item_out)
                if resp:
                    fast_resps.append(resp)
            if fast_resps:
                yield ("chunk", "\n\n".join(fast_resps))
                return

        # Step 2: Per query o operazioni complesse, genera sintesi fluida via LLM
        step2_metrics: dict[str, Any] = {}
        for chunk in stream_chat_response(
            base_url,
            model,
            executed_messages,
            temperature,
            max_tokens,
            enable_thinking=enable_thinking,
            metrics=step2_metrics,
        ):
            yield ("chunk", chunk)
        if step2_metrics:
            yield ("metrics", step2_metrics)


# ---------------------------------------------------------------------------
# Modello Decisionale Locale (Rizzo Flow / Spark-X2.5 su porta 8017)
# ---------------------------------------------------------------------------
def check_decision_server(
    base_url: str = DEFAULT_DECISION_URL,
) -> tuple[bool, str, str]:
    """Verifica lo stato del server del modello decisionale (Rizzo Flow su porta 8017)."""
    base = base_url.rstrip("/")
    try:
        r = requests.get(f"{base}/health", timeout=2.5)
        if r.status_code == 200:
            data = r.json()
            model_info = data.get("model", {})
            model_name = model_info.get("source") or model_info.get("gguf_source") or "Spark-X2.5-1.7B"
            return True, model_name, ""
        return False, "", f"Status {r.status_code}"
    except Exception as exc:
        return False, "", str(exc)


def should_use_thinking(
    prompt: str,
    base_url: str = DEFAULT_DECISION_URL,
    timeout: float = 6.0,
) -> tuple[bool, str, dict[str, Any]]:
    """Interroga il modello decisionale locale (127.0.0.1:8017) per determinare se è necessaria la thinking mode.

    Restituisce:
    - need_thinking (bool): True se il modello ritiene necessario il ragionamento profondo,
                            False se è sufficiente una risposta diretta (e quindi va aggiunto /no_think).
    - choice (str): 'yes' o 'no'.
    - details (dict): dizionario con probabilità, timing e diagnostica.
    """
    clean_p = (prompt or "").strip()
    if not clean_p:
        return False, "no", {"status": "empty_prompt"}

    base = base_url.rstrip("/")
    payload = {
        "state": clean_p,
        "questions": {
            "need_thinking": {
                "type": "choice",
                "policy": {"allow_abstain": False},
                "instructions": (
                    "Determine whether answering the user prompt requires deep step-by-step thinking/reasoning "
                    "(math problem, programming code, complex logic, detailed analysis) or if a quick direct answer "
                    "without thinking mode is sufficient (greeting, factual lookup, schedule, casual chat)."
                ),
                "options": [
                    {
                        "id": "yes",
                        "description": "Thinking mode is required (complex task, math, coding, multi-step problem solving).",
                    },
                    {
                        "id": "no",
                        "description": "Thinking mode is NOT required (simple greeting, schedule check, holiday balance, quick answer).",
                    },
                ],
            }
        },
    }

    try:
        resp = requests.post(f"{base}/v1/decisions", json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            answer = data.get("answers", {}).get("need_thinking", {})
            probs = answer.get("probabilities", {})

            # Valuta sia choice che le probabilità relative
            prob_yes = probs.get("yes", 0.0)
            prob_no = probs.get("no", 0.0)

            # Scelta preferenziale
            choice = answer.get("choice")
            if not choice:
                choice = "yes" if prob_yes > prob_no else "no"

            need_thinking = (choice == "yes")
            return need_thinking, choice, {
                "status": "ok",
                "choice": choice,
                "probabilities": probs,
                "total_ms": data.get("timing", {}).get("total_seconds", 0) * 1000,
            }
    except Exception as exc:
        # In caso di mancata risposta o offline, fallback a thinking mode attivo
        return True, "fallback_error", {"error": str(exc)}

    return True, "fallback", {}


def format_qwen_prompt(prompt: str, need_thinking: bool) -> str:
    """Formatta il prompt per Qwen: aggiunge /no_think all'inizio se la thinking mode non è necessaria."""
    p_clean = (prompt or "").strip()
    if not need_thinking:
        if not p_clean.startswith("/no_think"):
            return f"/no_think {p_clean}"
    return p_clean


def classify_intent_and_routing(
    prompt: str,
    base_url: str = DEFAULT_DECISION_URL,
    timeout: float = 3.5,
) -> dict[str, Any]:
    """Interroga il modello decisionale locale (127.0.0.1:8017) per determinare intent e need_thinking in una singola chiamata batch.

    Restituisce un dizionario con:
    - intent (str): 'chat', 'agenda', 'ferie', 'analytics', 'tracking'
    - need_thinking (bool): True se serve ragionamento profondo, False per risposta diretta
    - confidence (float): confidenza della classificazione
    - total_ms (float): tempo impiegato dal modello decisionale
    - status (str): 'ok', 'fallback', 'empty'
    """
    clean_p = (prompt or "").strip()
    if not clean_p:
        return {"intent": "chat", "need_thinking": False, "confidence": 1.0, "total_ms": 0.0, "status": "empty"}

    base = base_url.rstrip("/")
    payload = {
        "state": clean_p,
        "questions": {
            "intent": {
                "type": "choice",
                "policy": {"allow_abstain": False},
                "instructions": "Determina la categoria funzionale principale richiesta dall'utente.",
                "options": [
                    {"id": "chat", "description": "Conversazione generale, saluti, domande generali senza dati o azioni"},
                    {"id": "agenda", "description": "Consultazione o gestione impegni di calendario, slot orari o riunioni"},
                    {"id": "ferie", "description": "Richiesta ferie, permessi, assenze o saldo giorni"},
                    {"id": "analytics", "description": "Fatturato, vendite, resi, paia spedite, top articoli o canali"},
                    {"id": "tracking", "description": "Tracciamento stato spedizioni e pacchi GLS, UPS o DHL"},
                ],
            },
            "need_thinking": {
                "type": "choice",
                "policy": {"allow_abstain": False},
                "instructions": "Determina se la richiesta richiede ragionamento logico/matematico complesso o semplice esecuzione/risposta diretta.",
                "options": [
                    {"id": "no", "description": "Risposta diretta o azione immediata (non serve thinking)"},
                    {"id": "yes", "description": "Problema logico/matematico o pianificazione complessa (serve thinking)"},
                ],
            },
        },
    }

    try:
        resp = requests.post(f"{base}/v1/decisions", json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            ans = data.get("answers", {})
            intent_choice = ans.get("intent", {}).get("choice", "chat")
            intent_prob = ans.get("intent", {}).get("probabilities", {}).get(intent_choice, 0.0)
            think_choice = ans.get("need_thinking", {}).get("choice", "no")
            need_thinking = (think_choice == "yes")
            total_ms = data.get("timing", {}).get("total_seconds", 0) * 1000

            return {
                "intent": intent_choice,
                "need_thinking": need_thinking,
                "confidence": intent_prob,
                "total_ms": total_ms,
                "status": "ok",
            }
    except Exception as exc:
        return {"intent": "chat", "need_thinking": False, "confidence": 0.0, "total_ms": 0.0, "status": f"error: {exc}"}

    return {"intent": "chat", "need_thinking": False, "confidence": 0.0, "total_ms": 0.0, "status": "fallback"}


