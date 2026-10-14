"""Modulo per la gestione dell'Agenda personale avanzata per ciascun utente.

Funzionalità:
- Tabella SQLite `agenda_eventi` con isolamento rigoroso per email utente.
- Controllo rigoroso sovrapposizioni e conflitti di orario (Overlap Prevention).
- Rispetto degli orari lavorativi contrattuali dell'utente (da tabella dipendenti) e pausa pranzo.
- Rilevamento ferie, assenze e permessi orari (da tabella ferie_assenze).
- Calcolo matematico dei minuti e frazioni di tempo liberi (disponibilità e slot liberi).
- Definizione schemi Tool / Function Calling compatibili con standard OpenAI / llama.cpp.
- Esecutore di chiamate tool per il chatbot.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_dt(val: str) -> datetime | None:
    """Esegue il parsing flessibile di stringhe data/ora normalizzandole in datetime locale."""
    if not val:
        return None
    val_clean = str(val).strip().replace("T", " ")
    # Rimuovi timezone offset se presente (es. +00:00 o Z)
    if val_clean.endswith("Z"):
        val_clean = val_clean[:-1].strip()
    if "+" in val_clean:
        val_clean = val_clean.split("+")[0].strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(val_clean, fmt)
        except ValueError:
            continue
    return None


def format_dt(dt: datetime) -> str:
    """Formatta un datetime nello standard 'YYYY-MM-DD HH:MM'."""
    return dt.strftime("%Y-%m-%d %H:%M")


def init_agenda_tables(conn: sqlite3.Connection) -> None:
    """Crea la tabella per l'agenda degli utenti se non esiste."""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS agenda_eventi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        titolo TEXT NOT NULL,
        data_inizio TEXT NOT NULL,         -- Formato 'YYYY-MM-DD HH:MM'
        data_fine TEXT,                   -- Formato 'YYYY-MM-DD HH:MM'
        luogo TEXT DEFAULT '',
        categoria TEXT DEFAULT 'impegno', -- 'riunione', 'promemoria', 'scadenza', 'chiamata', 'impegno', 'personale'
        note TEXT DEFAULT '',
        completato INTEGER DEFAULT 0,      -- 0=attivo, 1=completato
        creato_il TEXT NOT NULL,
        aggiornato_il TEXT NOT NULL
    );
    """)
    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_agenda_email_inizio ON agenda_eventi(email, data_inizio);
    """)
    conn.commit()


def get_orari_lavorativi(conn: sqlite3.Connection, email: str) -> dict[str, Any]:
    """Recupera gli orari contrattuali di lavoro dell'utente dalla tabella dipendenti."""
    email_clean = (email or "").strip().lower()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT nome, mattina_inizio, mattina_fine, pomeriggio_inizio, pomeriggio_fine
        FROM dipendenti
        WHERE LOWER(email) = ?
        """,
        (email_clean,),
    ).fetchone()

    if row:
        return {
            "nome": row[0],
            "mattina_inizio": row[1] or "08:00",
            "mattina_fine": row[2] or "12:00",
            "pomeriggio_inizio": row[3] or "14:00",
            "pomeriggio_fine": row[4] or "18:00",
            "fascia_mattina": f"{row[1] or '08:00'} - {row[2] or '12:00'}",
            "fascia_pomeriggio": f"{row[3] or '14:00'} - {row[4] or '18:00'}",
        }

    return {
        "nome": email_clean.split("@")[0].replace(".", " ").title(),
        "mattina_inizio": "07:00",
        "mattina_fine": "12:00",
        "pomeriggio_inizio": "14:00",
        "pomeriggio_fine": "17:00",
        "fascia_mattina": "07:00 - 12:00",
        "fascia_pomeriggio": "14:00 - 17:00",
    }


def get_assenze_giorno(conn: sqlite3.Connection, email: str, data_giorno: str) -> list[dict[str, Any]]:
    """Recupera ferie o permessi dell'utente per una determinata data (YYYY-MM-DD)."""
    orari = get_orari_lavorativi(conn, email)
    nome_dipendente = orari["nome"]
    data_clean = str(data_giorno).strip()[:10]

    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note
        FROM ferie_assenze
        WHERE LOWER(nome) = LOWER(?)
          AND data_inizio <= ?
          AND data_fine >= ?
        """,
        (nome_dipendente, data_clean, data_clean),
    ).fetchall()

    assenze = []
    for r in rows:
        assenze.append({
            "id": r[0],
            "tipo": r[4],
            "giorni": r[5],
            "dettaglio": r[6] or "",
            "note": r[7] or "",
        })
    return assenze


def verifica_conflitti_orario(
    conn: sqlite3.Connection,
    email: str,
    dt_inizio: datetime,
    dt_fine: datetime,
    escludi_id: int | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Verifica se l'intervallo temporale [dt_inizio, dt_fine] si sovrappone a impegni attivi già registrati.

    Formula di overlap:
        existing_inizio < new_fine AND existing_fine > new_inizio
    """
    email_clean = (email or "").strip().lower()
    data_giorno = dt_inizio.strftime("%Y-%m-%d")

    # Recupera tutti gli eventi attivi per quel giorno o a cavallo
    cur = conn.cursor()
    query = """
        SELECT id, titolo, data_inizio, data_fine, luogo, categoria
        FROM agenda_eventi
        WHERE LOWER(email) = ?
          AND completato = 0
          AND (data_inizio LIKE ? OR data_fine LIKE ?)
    """
    params: list[Any] = [email_clean, f"{data_giorno}%", f"{data_giorno}%"]
    if escludi_id:
        query += " AND id != ?"
        params.append(int(escludi_id))

    rows = cur.execute(query, tuple(params)).fetchall()

    for r in rows:
        ev_id, ev_titolo, ev_start_str, ev_end_str, ev_luogo, ev_cat = r
        ev_start = parse_dt(ev_start_str)
        if not ev_start:
            continue
        # Se fine mancante, assumiamo default 30 minuti
        ev_end = parse_dt(ev_end_str) if ev_end_str else ev_start + timedelta(minutes=30)
        if not ev_end:
            ev_end = ev_start + timedelta(minutes=30)

        # Controllo sovrapposizione stretta
        if ev_start < dt_fine and ev_end > dt_inizio:
            conflitto_info = {
                "id": ev_id,
                "titolo": ev_titolo,
                "inizio": format_dt(ev_start),
                "fine": format_dt(ev_end),
                "luogo": ev_luogo or "",
                "categoria": ev_cat,
            }
            msg = f"Orario già occupato: hai già l'impegno '{ev_titolo}' dalle {ev_start.strftime('%H:%M')} alle {ev_end.strftime('%H:%M')}."
            return True, msg, conflitto_info

    return False, "", None


def verifica_orario_lavorativo(
    conn: sqlite3.Connection,
    email: str,
    dt_inizio: datetime,
    dt_fine: datetime,
) -> tuple[bool, str]:
    """Verifica che l'evento rispetti gli orari lavorativi contrattuali e la pausa pranzo."""
    orari = get_orari_lavorativi(conn, email)

    def _to_min(hh_mm: str) -> int:
        h, m = map(int, hh_mm.split(":"))
        return h * 60 + m

    m_start = _to_min(orari["mattina_inizio"])
    m_end = _to_min(orari["mattina_fine"])
    p_start = _to_min(orari["pomeriggio_inizio"])
    p_end = _to_min(orari["pomeriggio_fine"])

    ev_start_m = dt_inizio.hour * 60 + dt_inizio.minute
    ev_end_m = dt_fine.hour * 60 + dt_fine.minute

    # Pausa pranzo: tra mattina_fine e pomeriggio_inizio
    if ev_start_m < p_start and ev_end_m > m_end:
        # Se l'evento cade o si sovrappone alla pausa pranzo
        if not (ev_start_m >= m_start and ev_end_m <= m_end):
            return False, f"L'orario ricade nella pausa pranzo contrattuale ({orari['mattina_fine']} - {orari['pomeriggio_inizio']})."

    # Fuori turno (prima dell'inizio mattina o dopo la fine pomeriggio)
    if ev_start_m < m_start:
        return False, f"L'orario inizia prima dell'inizio del turno lavorativo ({orari['mattina_inizio']})."
    if ev_end_m > p_end:
        return False, f"L'orario termina dopo la fine del turno lavorativo ({orari['pomeriggio_fine']})."

    return True, ""


def calcola_disponibilita_giorno(
    conn: sqlite3.Connection,
    email: str,
    data_giorno: str,
    durata_minuti_richiesta: int = 0,
) -> dict[str, Any]:
    """Calcola gli slot orari liberi, minuti residui e frazioni di tempo per un determinato giorno."""
    data_clean = str(data_giorno).strip()[:10]
    dt_day = parse_dt(data_clean)
    if not dt_day:
        return {"success": False, "error": f"Formato data '{data_giorno}' non valido (usa YYYY-MM-DD)."}

    orari = get_orari_lavorativi(conn, email)

    # 1. Controlla ferie e assenze
    assenze = get_assenze_giorno(conn, email, data_clean)
    for ass in assenze:
        tipo = ass["tipo"].lower()
        if "ferie" in tipo or "malattia" in tipo:
            return {
                "success": True,
                "data": data_clean,
                "disponibile": False,
                "motivo": f"Assente per {ass['tipo']} (tutto il giorno)",
                "minuti_lavorativi": 0,
                "minuti_liberi": 0,
                "minuti_occupati": 0,
                "slot_liberi": [],
                "eventi": [],
            }

    def _to_min(hh_mm: str) -> int:
        h, m = map(int, hh_mm.split(":"))
        return h * 60 + m

    def _to_hhmm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    m_start = _to_min(orari["mattina_inizio"])
    m_end = _to_min(orari["mattina_fine"])
    p_start = _to_min(orari["pomeriggio_inizio"])
    p_end = _to_min(orari["pomeriggio_fine"])

    # Finestre lavorative iniziali
    finestre = [(m_start, m_end), (p_start, p_end)]

    # Recupera tutti gli eventi attivi del giorno
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, titolo, data_inizio, data_fine, luogo, categoria
        FROM agenda_eventi
        WHERE LOWER(email) = ?
          AND completato = 0
          AND (data_inizio LIKE ? OR data_fine LIKE ?)
        ORDER BY data_inizio ASC
        """,
        (email.strip().lower(), f"{data_clean}%", f"{data_clean}%"),
    ).fetchall()

    busy_intervals: list[tuple[int, int, str]] = []
    eventi_list: list[dict[str, Any]] = []

    for r in rows:
        ev_id, ev_titolo, ev_start_str, ev_end_str, ev_luogo, ev_cat = r
        ev_start = parse_dt(ev_start_str)
        if not ev_start:
            continue
        ev_end = parse_dt(ev_end_str) if ev_end_str else ev_start + timedelta(minutes=30)
        if not ev_end:
            ev_end = ev_start + timedelta(minutes=30)

        s_m = ev_start.hour * 60 + ev_start.minute
        e_m = ev_end.hour * 60 + ev_end.minute

        busy_intervals.append((s_m, e_m, ev_titolo))
        eventi_list.append({
            "id": ev_id,
            "titolo": ev_titolo,
            "inizio": format_dt(ev_start),
            "fine": format_dt(ev_end),
            "luogo": ev_luogo or "",
            "categoria": ev_cat,
        })

    # Algoritmo di sottrazione degli intervalli
    slot_liberi_raw: list[tuple[int, int]] = []
    for w_start, w_end in finestre:
        curr_pieces = [(w_start, w_end)]
        for b_start, b_end, _ in busy_intervals:
            next_pieces = []
            for p_start, p_end in curr_pieces:
                if b_end <= p_start or b_start >= p_end:
                    next_pieces.append((p_start, p_end))
                else:
                    if b_start > p_start:
                        next_pieces.append((p_start, b_start))
                    if b_end < p_end:
                        next_pieces.append((b_end, p_end))
            curr_pieces = next_pieces
        slot_liberi_raw.extend(curr_pieces)

    minuti_totali_lavoro = (m_end - m_start) + (p_end - p_start)
    minuti_liberi = sum(end - start for start, end in slot_liberi_raw)
    minuti_occupati = minuti_totali_lavoro - minuti_liberi

    slot_formattati = []
    for start, end in slot_liberi_raw:
        dur = end - start
        if dur > 0:
            if durata_minuti_richiesta <= 0 or dur >= durata_minuti_richiesta:
                slot_formattati.append({
                    "inizio": _to_hhmm(start),
                    "fine": _to_hhmm(end),
                    "durata_minuti": dur,
                    "descrizione": f"Dalle {_to_hhmm(start)} alle {_to_hhmm(end)} ({dur} min liberi)",
                })

    return {
        "success": True,
        "data": data_clean,
        "orari_contrattuali": {
            "mattina": orari["fascia_mattina"],
            "pomeriggio": orari["fascia_pomeriggio"],
            "pausa_pranzo": f"{orari['mattina_fine']} - {orari['pomeriggio_inizio']}",
        },
        "minuti_lavorativi": minuti_totali_lavoro,
        "minuti_occupati": max(0, minuti_occupati),
        "minuti_liberi": minuti_liberi,
        "slot_liberi": slot_formattati,
        "eventi": eventi_list,
    }


def format_minuti_str(m: int) -> str:
    """Formatta minuti in ore e minuti leggibili (es. '3 ore', '1h 30m', '45 min')."""
    h = m // 60
    rem = m % 60
    if h > 0 and rem > 0:
        return f"{h}h {rem}m"
    elif h > 0:
        return f"{h} ore" if h > 1 else "1 ora"
    else:
        return f"{rem} min"


def format_daily_calendar_markdown(disp_data: dict[str, Any]) -> str:
    """Formatta i dati di disponibilità come un calendario giornaliero visuale strutturato in fasce orarie."""
    if not disp_data.get("success"):
        return f"⚠️ Errore nel calcolo del calendario: {disp_data.get('error', 'Dati non disponibili')}"

    data_str = disp_data.get("data", "")
    try:
        dt = datetime.strptime(data_str, "%Y-%m-%d")
        giorni_settimana = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
        mesi = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
        titolo_data = f"{giorni_settimana[dt.weekday()]} {dt.day} {mesi[dt.month]} {dt.year}"
    except Exception:
        titolo_data = data_str

    if not disp_data.get("disponibile", True):
        return (
            f"### 📅 Calendario Giornaliero – {titolo_data}\n\n"
            f"🏖️ **{disp_data.get('motivo', 'Assenza / Ferie')}**\n\n"
            f"*Non sono previsti slot lavorativi per questa giornata.*"
        )

    orari = disp_data.get("orari_contrattuali", {})
    m_fascia = orari.get("mattina", "07:00 - 12:00")
    p_fascia = orari.get("pomeriggio", "14:00 - 17:00")

    # Unisci slot liberi ed eventi in un'unica timeline ordinata
    timeline = []
    for s in disp_data.get("slot_liberi", []):
        timeline.append({
            "tipo": "libero",
            "inizio": s["inizio"],
            "fine": s["fine"],
            "durata": s["durata_minuti"],
            "desc": f"Disponibile ({format_minuti_str(s['durata_minuti'])})",
            "titolo": "Libero",
        })

    for ev in disp_data.get("eventi", []):
        s_time = ev["inizio"].split(" ")[-1] if " " in ev["inizio"] else ev["inizio"]
        e_time = ev["fine"].split(" ")[-1] if " " in ev["fine"] else ev["fine"]
        loc = f" *({ev['luogo']})*" if ev.get("luogo") else ""
        cat = f" `[{ev.get('categoria', 'impegno').upper()}]`" if ev.get("categoria") else ""
        timeline.append({
            "tipo": "occupato",
            "inizio": s_time,
            "fine": e_time,
            "durata": 0,
            "desc": f"**{ev['titolo']}**{loc}{cat}",
            "titolo": ev["titolo"],
        })

    # Ordina cronologicamente
    timeline.sort(key=lambda x: x["inizio"])

    m_end = m_fascia.split("-")[1].strip() if "-" in m_fascia else "12:00"
    p_start = p_fascia.split("-")[0].strip() if "-" in p_fascia else "14:00"

    mattina_items = [t for t in timeline if t["fine"] <= m_end or t["inizio"] < m_end]
    pomeriggio_items = [t for t in timeline if t["inizio"] >= p_start or t["fine"] > p_start]

    lines = [f"### 📅 Calendario Giornaliero – {titolo_data}\n"]

    # Sezione Mattina
    lines.append(f"#### 🌅 Mattina ({m_fascia})")
    if mattina_items:
        lines.append("| Fascia Oraria | Stato | Dettaglio / Impegno |")
        lines.append("| :--- | :--- | :--- |")
        for item in mattina_items:
            badge = "🟢 **Libero**" if item["tipo"] == "libero" else "🔴 **Occupato**"
            lines.append(f"| **{item['inizio']} – {item['fine']}** | {badge} | {item['desc']} |")
    else:
        lines.append("*Nessuno slot attivo registrato.*")

    lines.append("")

    # Sezione Pomeriggio
    lines.append(f"#### 🌇 Pomeriggio ({p_fascia})")
    if pomeriggio_items:
        lines.append("| Fascia Oraria | Stato | Dettaglio / Impegno |")
        lines.append("| :--- | :--- | :--- |")
        for item in pomeriggio_items:
            badge = "🟢 **Libero**" if item["tipo"] == "libero" else "🔴 **Occupato**"
            lines.append(f"| **{item['inizio']} – {item['fine']}** | {badge} | {item['desc']} |")
    else:
        lines.append("*Nessuno slot attivo registrato.*")

    m_tot = disp_data.get("minuti_lavorativi", 0)
    m_lib = disp_data.get("minuti_liberi", 0)
    m_occ = disp_data.get("minuti_occupati", 0)
    lines.append("")
    lines.append("---")
    lines.append(f"📊 **Riepilogo:** **{format_minuti_str(m_lib)} disponibili** su {format_minuti_str(m_tot)} lavorative ({format_minuti_str(m_occ)} occupati).")

    return "\n".join(lines)


def crea_evento(
    conn: sqlite3.Connection,
    email: str,
    titolo: str,
    data_inizio: str,
    data_fine: str | None = None,
    luogo: str = "",
    categoria: str = "impegno",
    note: str = "",
    forza_inserimento: bool = False,
) -> dict[str, Any]:
    """Crea un nuovo impegno nell'agenda dell'utente verificando conflitti, ferie e orari lavorativi."""
    email_clean = (email or "").strip().lower()
    titolo_clean = (titolo or "").strip()
    data_inizio_clean = (data_inizio or "").strip()

    if not email_clean or not titolo_clean or not data_inizio_clean:
        return {"success": False, "error": "Email, titolo e data_inizio sono obbligatori."}

    dt_start = parse_dt(data_inizio_clean)
    if not dt_start:
        return {"success": False, "error": f"Formato data_inizio '{data_inizio_clean}' non valido."}

    # Se data_fine manca, calcola default (30 minuti)
    if data_fine:
        dt_end = parse_dt(data_fine)
        if not dt_end or dt_end <= dt_start:
            dt_end = dt_start + timedelta(minutes=30)
    else:
        dt_end = dt_start + timedelta(minutes=30)

    start_formatted = format_dt(dt_start)
    end_formatted = format_dt(dt_end)
    giorno_str = dt_start.strftime("%Y-%m-%d")

    # 1. Verifica ferie / assenze
    if not forza_inserimento:
        assenze = get_assenze_giorno(conn, email_clean, giorno_str)
        for ass in assenze:
            tipo = ass["tipo"].lower()
            if "ferie" in tipo or "malattia" in tipo:
                return {
                    "success": False,
                    "in_ferie": True,
                    "error": f"Impossibile fissare l'impegno: il {giorno_str} sei in '{ass['tipo']}'.",
                }

    # 2. Verifica rispetto turno di lavoro contrattuale
    if not forza_inserimento:
        orario_ok, err_orario = verifica_orario_lavorativo(conn, email_clean, dt_start, dt_end)
        if not orario_ok:
            return {
                "success": False,
                "fuori_orario": True,
                "error": f"Attenzione: {err_orario}",
            }

    # 3. Verifica rigorosa sovrapposizione e conflitti di orario
    if not forza_inserimento:
        ha_conflitto, msg_conflitto, conf_info = verifica_conflitti_orario(conn, email_clean, dt_start, dt_end)
        if ha_conflitto:
            return {
                "success": False,
                "conflitto": True,
                "error": msg_conflitto,
                "evento_in_conflitto": conf_info,
            }

    # 4. Inserimento nel database
    now = _now_iso()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO agenda_eventi (
            email, titolo, data_inizio, data_fine, luogo, categoria, note, completato, creato_il, aggiornato_il
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            email_clean,
            titolo_clean,
            start_formatted,
            end_formatted,
            (luogo or "").strip(),
            (categoria or "impegno").strip().lower(),
            (note or "").strip(),
            now,
            now,
        ),
    )
    conn.commit()
    evento_id = cur.lastrowid
    return {
        "success": True,
        "evento_id": evento_id,
        "titolo": titolo_clean,
        "data_inizio": start_formatted,
        "data_fine": end_formatted,
        "luogo": (luogo or "").strip(),
        "categoria": (categoria or "impegno").strip().lower(),
        "messaggio": f"Impegno '{titolo_clean}' registrato per il {start_formatted} - {dt_end.strftime('%H:%M')}.",
    }


def get_eventi_utente(
    conn: sqlite3.Connection,
    email: str,
    data_da: str | None = None,
    data_a: str | None = None,
    solo_attivi: bool = False,
) -> list[dict[str, Any]]:
    """Recupera gli eventi dell'agenda di un determinato utente."""
    email_clean = (email or "").strip().lower()
    query = "SELECT id, email, titolo, data_inizio, data_fine, luogo, categoria, note, completato, creato_il FROM agenda_eventi WHERE email = ?"
    params: list[Any] = [email_clean]

    if data_da:
        val_da = str(data_da).strip()
        query += " AND data_inizio >= ?"
        params.append(val_da)
    if data_a:
        val_a = str(data_a).strip()
        if len(val_a) == 10:
            val_a += " 23:59:59"
        query += " AND data_inizio <= ?"
        params.append(val_a)
    if solo_attivi:
        query += " AND completato = 0"

    query += " ORDER BY data_inizio ASC"
    cur = conn.cursor()
    rows = cur.execute(query, tuple(params)).fetchall()

    eventi = []
    for r in rows:
        eventi.append({
            "id": r[0],
            "email": r[1],
            "titolo": r[2],
            "data_inizio": r[3],
            "data_fine": r[4] or "",
            "luogo": r[5] or "",
            "categoria": r[6] or "impegno",
            "note": r[7] or "",
            "completato": bool(r[8]),
            "creato_il": r[9],
        })
    return eventi


def elimina_evento(conn: sqlite3.Connection, email: str, evento_id: Any) -> dict[str, Any]:
    """Elimina uno o più eventi appartenenti all'utente specificato."""
    email_clean = (email or "").strip().lower()
    cur = conn.cursor()

    # Supporta int singolo, lista di int o stringhe separate da virgola (es. '3, 5' o [3, 5])
    ids_to_del: list[int] = []
    if isinstance(evento_id, (list, tuple)):
        for x in evento_id:
            try:
                ids_to_del.append(int(x))
            except (ValueError, TypeError):
                continue
    elif isinstance(evento_id, str) and ("," in evento_id or " " in evento_id):
        for part in evento_id.replace(",", " ").split():
            try:
                ids_to_del.append(int(part))
            except (ValueError, TypeError):
                continue
    else:
        try:
            ids_to_del.append(int(evento_id))
        except (ValueError, TypeError):
            return {"success": False, "error": f"ID evento non valido: {evento_id}"}

    if not ids_to_del:
        return {"success": False, "error": "Nessun ID evento valido fornito."}

    placeholders = ",".join(["?"] * len(ids_to_del))
    cur.execute(
        f"DELETE FROM agenda_eventi WHERE id IN ({placeholders}) AND LOWER(email) = ?",
        (*ids_to_del, email_clean),
    )
    conn.commit()
    count = cur.rowcount
    if count > 0:
        return {
            "success": True,
            "eliminati": count,
            "messaggio": f"Eliminati {count} impegni (ID: {', '.join(map(str, ids_to_del))}) con successo.",
        }
    return {"success": False, "error": f"Nessun evento trovato con gli ID specificati per l'utente."}


def elimina_eventi_giorno(conn: sqlite3.Connection, email: str, data_giorno: str) -> dict[str, Any]:
    """Elimina tutti gli impegni dell'utente per una determinata data (YYYY-MM-DD)."""
    email_clean = (email or "").strip().lower()
    data_clean = str(data_giorno).strip()[:10]
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM agenda_eventi WHERE LOWER(email) = ? AND data_inizio LIKE ?",
        (email_clean, f"{data_clean}%"),
    )
    conn.commit()
    count = cur.rowcount
    return {
        "success": True,
        "eliminati": count,
        "messaggio": f"Eliminati {count} impegni per la data {data_clean}.",
    }


def segna_completato(conn: sqlite3.Connection, email: str, evento_id: Any, completato: bool = True) -> dict[str, Any]:
    """Contrassegna uno o più impegni come completati o attivi."""
    email_clean = (email or "").strip().lower()
    now = _now_iso()
    cur = conn.cursor()

    ids: list[int] = []
    if isinstance(evento_id, (list, tuple)):
        for x in evento_id:
            try:
                ids.append(int(x))
            except Exception:
                continue
    elif isinstance(evento_id, str) and "," in evento_id:
        for p in evento_id.split(","):
            try:
                ids.append(int(p.strip()))
            except Exception:
                continue
    else:
        try:
            ids.append(int(evento_id))
        except Exception:
            return {"success": False, "error": f"ID evento non valido: {evento_id}"}

    if not ids:
        return {"success": False, "error": "Nessun ID evento valido."}

    placeholders = ",".join(["?"] * len(ids))
    cur.execute(
        f"UPDATE agenda_eventi SET completato = ?, aggiornato_il = ? WHERE id IN ({placeholders}) AND LOWER(email) = ?",
        (1 if completato else 0, now, *ids, email_clean),
    )
    conn.commit()
    stato = "completato" if completato else "attivo"
    if cur.rowcount > 0:
        return {"success": True, "messaggio": f"{cur.rowcount} impegni contrassegnati come {stato}."}
    return {"success": False, "error": f"Nessun evento trovato per l'utente con gli ID specificati."}


# ---------------------------------------------------------------------------
# Schemi dei Tool Function Calling per l'LLM (OpenAI-compatible)
# ---------------------------------------------------------------------------
AGENDA_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "agenda_inserisci_impegno",
            "description": "Inserisce un nuovo appuntamento o riunione nell'agenda dell'utente. Blocca automaticamente sovrapposizioni e rispetta gli orari di lavoro.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titolo": {
                        "type": "string",
                        "description": "Titolo o oggetto dell'impegno (es. 'Riunione logistica', 'Chiamata cliente X')",
                    },
                    "data_inizio": {
                        "type": "string",
                        "description": "Data e ora inizio nel formato 'YYYY-MM-DD HH:MM' (es. '2026-10-15 15:30')",
                    },
                    "data_fine": {
                        "type": "string",
                        "description": "Data e ora fine nel formato 'YYYY-MM-DD HH:MM' (opzionale, default: 30 minuti dopo l'inizio)",
                    },
                    "categoria": {
                        "type": "string",
                        "enum": ["riunione", "promemoria", "scadenza", "chiamata", "impegno", "personale"],
                        "description": "Categoria dell'impegno (default: riunione)",
                    },
                    "luogo": {
                        "type": "string",
                        "description": "Luogo fisico o link telematico (Google Meet, Teams, Sala riunioni)",
                    },
                    "note": {
                        "type": "string",
                        "description": "Note o dettagli aggiuntivi",
                    },
                },
                "required": ["titolo", "data_inizio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agenda_visualizza_impegni",
            "description": "Consulta gli impegni presenti nell'agenda personale dell'utente per un giorno o intervallo di date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_da": {
                        "type": "string",
                        "description": "Data iniziale da cui cercare nel formato 'YYYY-MM-DD' (opzionale)",
                    },
                    "data_a": {
                        "type": "string",
                        "description": "Data finale fino a cui cercare nel formato 'YYYY-MM-DD' (opzionale)",
                    },
                    "solo_attivi": {
                        "type": "boolean",
                        "description": "Se True, esclude gli impegni già completati (default: True)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agenda_trova_slot_liberi",
            "description": "Calcola la disponibilità esatta di una data, trovando tutti gli slot orari liberi, minuti residui e frazioni di ora disponibili.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "Data da analizzare nel formato 'YYYY-MM-DD' (es. '2026-10-14')",
                    },
                    "durata_minuti_richiesta": {
                        "type": "integer",
                        "description": "Durata minima dello slot libero cercato in minuti (es. 20, 30, 60, opzionale)",
                    },
                },
                "required": ["data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agenda_elimina_impegno",
            "description": "Cancella uno o più appuntamenti dall'agenda dato il loro ID numerico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "evento_id": {
                        "description": "ID numerico dell'evento o lista di ID da eliminare (es. 3 o [3, 5])",
                    },
                },
                "required": ["evento_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agenda_elimina_tutti_giorno",
            "description": "Cancella TUTTI gli impegni dell'agenda dell'utente per una determinata giornata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "Data di cui cancellare tutti gli impegni nel formato 'YYYY-MM-DD'",
                    },
                },
                "required": ["data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agenda_completa_impegno",
            "description": "Contrassegna uno o più impegni come completati dato il loro ID numerico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "evento_id": {
                        "description": "ID numerico dell'evento o lista di ID da contrassegnare come completato",
                    },
                },
                "required": ["evento_id"],
            },
        },
    },
]


def esegui_tool_agenda(
    conn: sqlite3.Connection,
    email: str,
    nome_funzione: str,
    argomenti: dict[str, Any],
) -> dict[str, Any]:
    """Esegue un tool dell'agenda e restituisce il risultato serializzabile in JSON per il modello o per il fast-path."""
    try:
        if nome_funzione == "agenda_inserisci_impegno":
            return crea_evento(
                conn=conn,
                email=email,
                titolo=argomenti.get("titolo", ""),
                data_inizio=argomenti.get("data_inizio", ""),
                data_fine=argomenti.get("data_fine"),
                luogo=argomenti.get("luogo", ""),
                categoria=argomenti.get("categoria", "riunione"),
                note=argomenti.get("note", ""),
                forza_inserimento=bool(argomenti.get("forza_inserimento", False)),
            )
        elif nome_funzione == "agenda_visualizza_impegni":
            eventi = get_eventi_utente(
                conn=conn,
                email=email,
                data_da=argomenti.get("data_da"),
                data_a=argomenti.get("data_a"),
                solo_attivi=bool(argomenti.get("solo_attivi", True)),
            )
            return {"success": True, "totale_trovati": len(eventi), "eventi": eventi}
        elif nome_funzione == "agenda_trova_slot_liberi":
            return calcola_disponibilita_giorno(
                conn=conn,
                email=email,
                data_giorno=argomenti.get("data", ""),
                durata_minuti_richiesta=int(argomenti.get("durata_minuti_richiesta", 0)),
            )
        elif nome_funzione == "agenda_elimina_impegno":
            ev_id = argomenti.get("evento_id")
            if ev_id is None:
                return {"success": False, "error": "evento_id mancante"}
            return elimina_evento(conn=conn, email=email, evento_id=ev_id)
        elif nome_funzione == "agenda_elimina_tutti_giorno":
            giorno = argomenti.get("data")
            if not giorno:
                return {"success": False, "error": "parametro 'data' mancante"}
            return elimina_eventi_giorno(conn=conn, email=email, data_giorno=giorno)
        elif nome_funzione == "agenda_completa_impegno":
            ev_id = argomenti.get("evento_id")
            if ev_id is None:
                return {"success": False, "error": "evento_id mancante"}
            return segna_completato(conn=conn, email=email, evento_id=ev_id, completato=True)
        else:
            return {"success": False, "error": f"Funzione sconosciuta: {nome_funzione}"}
    except Exception as exc:
        return {"success": False, "error": f"Eccezione durante l'esecuzione del tool: {exc}"}
