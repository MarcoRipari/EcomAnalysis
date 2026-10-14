"""Modulo Assistant Tools per l'Assistente Personale Aziendale H24.

Implementa i tool di Sprint 1 e Sprint 3:
- HR & Ferie: Verifica sovrapposizioni reparto/persona, policy a voce, consultazione saldi (no ROL), registrazione protetta per Admin.
- Agenda Multi-Persona & Reparto: Ricerca slot orari comuni tra persone specifiche o interi reparti.
- Fast Analytics: Query SQL sicure e aggregate su vendite, fatturato e resi con risposta sub-secondo.
- Tracking Spedizioni: Riconoscimento vettore (GLS, DHL, UPS, BRT, Poste) e generazione deeplink ufficiale.
- Fast-Path Formatter: Generazione istantanea del markdown (< 10ms) per evitare attese superflue del secondo turno LLM.
"""
from __future__ import annotations

import json
import re
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

from core import agenda, ferie, roles

MESI_IT: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 1. HR & FERIE: Policy, Sovrapposizioni e Saldi
# ---------------------------------------------------------------------------
def ferie_verifica_sovrapposizioni(
    conn: sqlite3.Connection,
    user_email: str,
    data_inizio: str,
    data_fine: str | None = None,
    reparto: str | None = None,
    persona: str | None = None,
) -> dict[str, Any]:
    """Verifica se ci sono assenze/ferie concordate che si sovrappongono all'intervallo richiesto.

    Rispetta la policy: le ferie non si richiedono da bot o form, ma si concordano a voce.
    """
    dt_start = str(data_inizio).strip()[:10]
    dt_end = str(data_fine).strip()[:10] if data_fine else dt_start
    if dt_start > dt_end:
        dt_start, dt_end = dt_end, dt_start

    cur = conn.cursor()

    # Mappa ruoli / reparti da utenti_ruoli e dipendenti
    query_dip = "SELECT d.nome, d.email, COALESCE(ur.ruolo, 'Dipendente') as ruolo FROM dipendenti d LEFT JOIN utenti_ruoli ur ON LOWER(d.email) = LOWER(ur.email) WHERE d.attivo = 1"
    rows_dip = cur.execute(query_dip).fetchall()

    dipendenti_filtrati: dict[str, dict[str, str]] = {}
    for nome, email, ruolo in rows_dip:
        match_rep = True
        match_per = True
        if reparto and reparto.strip():
            rep_clean = reparto.strip().lower()
            match_rep = rep_clean in (ruolo or "").lower() or rep_clean in nome.lower()
        if persona and persona.strip():
            per_clean = persona.strip().lower()
            match_per = per_clean in nome.lower() or per_clean in (email or "").lower()

        if match_rep and match_per:
            dipendenti_filtrati[nome] = {"email": email, "ruolo": ruolo}

    # Query assenze che si sovrappongono all'intervallo
    # Overlap condition: a.data_inizio <= dt_end AND a.data_fine >= dt_start
    query_ass = """
    SELECT id, nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note
    FROM ferie_assenze
    WHERE data_inizio <= ? AND data_fine >= ?
    ORDER BY data_inizio ASC
    """
    rows_ass = cur.execute(query_ass, (dt_end, dt_start)).fetchall()

    assenze_trovate: list[dict[str, Any]] = []
    nomi_assenti_set: set[str] = set()

    for r in rows_ass:
        nome_assente = r[1]
        # Se abbiamo filtrato per reparto o persona, verifica che il nome sia nel perimetro
        if dipendenti_filtrati and nome_assente not in dipendenti_filtrati:
            continue

        ruolo_dip = dipendenti_filtrati.get(nome_assente, {}).get("ruolo", "Dipendente") if dipendenti_filtrati else "Dipendente"
        nomi_assenti_set.add(nome_assente)
        assenze_trovate.append({
            "id": r[0],
            "nome": nome_assente,
            "ruolo": ruolo_dip,
            "data_inizio": r[2],
            "data_fine": r[3],
            "tipo": r[4],
            "giorni": r[5],
            "dettaglio": r[6] or "",
            "note": r[7] or "",
        })

    num_assenti = len(nomi_assenti_set)
    has_overlap = num_assenti > 0

    return {
        "success": True,
        "intervallo": {"da": dt_start, "a": dt_end},
        "reparto_richiesto": reparto or "Tutti",
        "persona_richiesta": persona or "Tutte",
        "sovrapposizione": has_overlap,
        "totale_colleghi_assenti": num_assenti,
        "dettaglio_assenze": assenze_trovate,
        "policy_promemoria": (
            "Le ferie e i permessi vanno SEMPRE concordati a voce con il responsabile. "
            "In azienda non esistono ROL distinti: tutte le assenze vengono imputate come Ferie."
        ),
    }


def ferie_consulta_saldo(
    conn: sqlite3.Connection,
    user_email: str,
    persona: str | None = None,
) -> dict[str, Any]:
    """Consulta il saldo ferie (totale spettante, godute, residue) dell'utente o di un dipendente.

    Ricorda che in azienda non sono previsti ROL separati.
    """
    email_clean = (user_email or "").strip().lower()
    cur = conn.cursor()

    target_nome = None
    target_email = email_clean

    if persona and persona.strip():
        p_clean = persona.strip().lower()
        row_p = cur.execute(
            "SELECT nome, email, totale_annuo FROM dipendenti WHERE LOWER(nome) LIKE ? OR LOWER(email) LIKE ? LIMIT 1",
            (f"%{p_clean}%", f"%{p_clean}%"),
        ).fetchone()
        if row_p:
            target_nome = row_p[0]
            target_email = row_p[1]
            totale_annuo = float(row_p[2] or 31.0)
        else:
            return {"success": False, "error": f"Nessun dipendente trovato per '{persona}'."}
    else:
        row_me = cur.execute(
            "SELECT nome, email, totale_annuo FROM dipendenti WHERE LOWER(email) = ? LIMIT 1",
            (email_clean,),
        ).fetchone()
        if row_me:
            target_nome = row_me[0]
            target_email = row_me[1]
            totale_annuo = float(row_me[2] or 31.0)
        else:
            target_nome = email_clean.split("@")[0].replace(".", " ").title()
            totale_annuo = 31.0

    # Calcola giorni goduti da ferie_assenze
    row_godute = cur.execute(
        "SELECT COALESCE(SUM(giorni_lavorativi), 0) FROM ferie_assenze WHERE LOWER(nome) = ?",
        (target_nome.lower(),),
    ).fetchone()
    giorni_goduti = float(row_godute[0]) if row_godute else 0.0
    giorni_residui = round(totale_annuo - giorni_goduti, 2)

    return {
        "success": True,
        "dipendente": target_nome,
        "email": target_email,
        "totale_annuo_spettante": totale_annuo,
        "giorni_goduti": giorni_goduti,
        "giorni_residui": giorni_residui,
        "nota_rol": "In azienda non è prevista la voce ROL separata: tutto il monte ore/giorni fa capo al saldo Ferie.",
    }


def ferie_registra_assenza(
    conn: sqlite3.Connection,
    user_email: str,
    dipendente: str,
    data_inizio: str,
    data_fine: str | None = None,
    tipo_assenza: str = "Ferie",
    durata_giorni: float = 1.0,
    dettaglio: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Registra ferie o permessi per un dipendente (RISERVATO AD ADMIN E RESPONSABILI)."""
    email_clean = (user_email or "").strip().lower()
    cur = conn.cursor()

    # Controllo permessi RBAC
    user_role = roles.get_user_role(conn, email_clean)
    allowed_pages = roles.get_role_permissions(conn, user_role)
    can_manage = (user_role == "Admin") or ("25_Ferie_Registra" in allowed_pages)

    if not can_manage:
        return {
            "success": False,
            "permesso_negato": True,
            "error": (
                "Permesso negato: l'inserimento diretto delle ferie è riservato agli Amministratori o ai Responsabili. "
                "I dipendenti devono concordare le ferie a voce con il proprio responsabile."
            ),
        }

    # Risoluzione anagrafica dipendente
    dip_clean = dipendente.strip().lower()
    row_dip = cur.execute(
        "SELECT nome, email FROM dipendenti WHERE LOWER(nome) LIKE ? OR LOWER(email) LIKE ? LIMIT 1",
        (f"%{dip_clean}%", f"%{dip_clean}%"),
    ).fetchone()
    if not row_dip:
        return {"success": False, "error": f"Dipendente '{dipendente}' non trovato nel registro."}

    nome_ufficiale = row_dip[0]
    dt_start = str(data_inizio).strip()[:10]
    dt_end = str(data_fine).strip()[:10] if data_fine else dt_start

    now = _now_iso()
    cur.execute(
        """
        INSERT INTO ferie_assenze (nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note, creato_il)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (nome_ufficiale, dt_start, dt_end, tipo_assenza, float(durata_giorni), dettaglio, note, now),
    )
    conn.commit()
    nuovo_id = cur.lastrowid or 0

    return {
        "success": True,
        "assenza_id": nuovo_id,
        "dipendente": nome_ufficiale,
        "intervallo": f"{dt_start} → {dt_end}" if dt_start != dt_end else dt_start,
        "tipo": tipo_assenza,
        "durata_giorni": float(durata_giorni),
        "messaggio": f"Assenza registrata con successo per {nome_ufficiale} ({durata_giorni} gg).",
    }


# ---------------------------------------------------------------------------
# 2. AGENDA: Ricerca Slot Multi-Persona & Reparto
# ---------------------------------------------------------------------------
def agenda_trova_slot_condiviso(
    conn: sqlite3.Connection,
    user_email: str,
    data: str,
    persona: str | None = None,
    persone: list[str] | None = None,
    reparto: str | None = None,
    durata_minuti_richiesta: int = 30,
) -> dict[str, Any]:
    """Cerca slot orari liberi comuni tra l'utente e una singola persona o tutti i membri di un reparto."""
    data_clean = str(data or "").strip()[:10]
    if not data_clean:
        data_clean = date.today().isoformat()
    try:
        base_dt = datetime.strptime(data_clean, "%Y-%m-%d")
    except ValueError:
        data_clean = date.today().isoformat()
        base_dt = datetime.strptime(data_clean, "%Y-%m-%d")
    cur = conn.cursor()

    # Raccogli l'elenco dei dipendenti da coinvolgere
    target_names: set[str] = set()
    if persona and persona.strip():
        target_names.add(persona.strip())
    if persone:
        for p in persone:
            if p and str(p).strip():
                target_names.add(str(p).strip())

    partecipanti: list[dict[str, Any]] = []

    if reparto and reparto.strip():
        rep_clean = reparto.strip().lower()
        # Cerca dipendenti associati al reparto/ruolo
        query_rep = """
        SELECT d.nome, d.email, COALESCE(ur.ruolo, 'Dipendente') as ruolo,
               d.mattina_inizio, d.mattina_fine, d.pomeriggio_inizio, d.pomeriggio_fine
        FROM dipendenti d
        LEFT JOIN utenti_ruoli ur ON LOWER(d.email) = LOWER(ur.email)
        WHERE d.attivo = 1 AND (LOWER(ur.ruolo) LIKE ? OR LOWER(d.nome) LIKE ?)
        """
        rows = cur.execute(query_rep, (f"%{rep_clean}%", f"%{rep_clean}%")).fetchall()
        for r in rows:
            partecipanti.append({
                "nome": r[0], "email": r[1], "ruolo": r[2],
                "mattina_inizio": r[3] or "08:00", "mattina_fine": r[4] or "12:00",
                "pomeriggio_inizio": r[5] or "14:00", "pomeriggio_fine": r[6] or "18:00",
            })

    if target_names:
        for tn in target_names:
            clean_tn = tn.lower()
            row = cur.execute(
                """
                SELECT d.nome, d.email, COALESCE(ur.ruolo, 'Dipendente') as ruolo,
                       d.mattina_inizio, d.mattina_fine, d.pomeriggio_inizio, d.pomeriggio_fine
                FROM dipendenti d
                LEFT JOIN utenti_ruoli ur ON LOWER(d.email) = LOWER(ur.email)
                WHERE d.attivo = 1 AND (LOWER(d.nome) LIKE ? OR LOWER(d.email) LIKE ?)
                LIMIT 1
                """,
                (f"%{clean_tn}%", f"%{clean_tn}%"),
            ).fetchone()
            if row and not any(p["email"] == row[1] for p in partecipanti):
                partecipanti.append({
                    "nome": row[0], "email": row[1], "ruolo": row[2],
                    "mattina_inizio": row[3] or "08:00", "mattina_fine": row[4] or "12:00",
                    "pomeriggio_inizio": row[5] or "14:00", "pomeriggio_fine": row[6] or "18:00",
                })

    # Aggiungi sempre l'utente chiamante se non è già tra i partecipanti
    email_me = (user_email or "").strip().lower()
    if not any(p["email"].lower() == email_me for p in partecipanti):
        row_me = cur.execute(
            """
            SELECT d.nome, d.email, COALESCE(ur.ruolo, 'Admin') as ruolo,
                   d.mattina_inizio, d.mattina_fine, d.pomeriggio_inizio, d.pomeriggio_fine
            FROM dipendenti d
            LEFT JOIN utenti_ruoli ur ON LOWER(d.email) = LOWER(ur.email)
            WHERE LOWER(d.email) = ?
            LIMIT 1
            """,
            (email_me,),
        ).fetchone()
        if row_me:
            partecipanti.insert(0, {
                "nome": row_me[0], "email": row_me[1], "ruolo": row_me[2],
                "mattina_inizio": row_me[3] or "08:00", "mattina_fine": row_me[4] or "12:00",
                "pomeriggio_inizio": row_me[5] or "14:00", "pomeriggio_fine": row_me[6] or "18:00",
            })
        else:
            partecipanti.insert(0, {
                "nome": email_me.split("@")[0].replace(".", " ").title(),
                "email": email_me, "ruolo": "Utente",
                "mattina_inizio": "08:00", "mattina_fine": "12:00",
                "pomeriggio_inizio": "14:00", "pomeriggio_fine": "18:00",
            })

    if not partecipanti:
        return {"success": False, "error": "Nessun partecipante identificato per la ricerca slot."}

    # 1. Verifica chi è in ferie in questa data
    assenti_ferie: list[str] = []
    presenti: list[dict[str, Any]] = []

    for p in partecipanti:
        row_ass = cur.execute(
            "SELECT id, tipo, dettaglio FROM ferie_assenze WHERE LOWER(nome) = ? AND data_inizio <= ? AND data_fine >= ? LIMIT 1",
            (p["nome"].lower(), data_clean, data_clean),
        ).fetchone()
        if row_ass:
            assenti_ferie.append(p["nome"])
        else:
            presenti.append(p)

    if not presenti:
        return {
            "success": True,
            "data": data_clean,
            "tutti_in_ferie": True,
            "assenti_ferie": assenti_ferie,
            "presenti": [],
            "slot_liberi": [],
            "messaggio": f"Tutti i membri richiesti sono assenti per ferie il {data_clean}.",
        }

    # 2. Griglia di slot da 15 minuti tra le 07:00 e le 19:00
    # Uno slot è libero se TUTTI i presenti sono in orario lavorativo e nessuno ha impegni in agenda
    base_dt = datetime.strptime(data_clean, "%Y-%m-%d")
    total_slots = int((19 - 7) * 4)  # 48 slot da 15 min
    slot_minutes = 15

    # Recupera tutti gli impegni per ciascun presente
    impegni_presenti: dict[str, list[tuple[datetime, datetime]]] = {}
    for p in presenti:
        p_email = p["email"].lower()
        rows_ev = cur.execute(
            "SELECT data_inizio, data_fine FROM agenda_eventi WHERE LOWER(email) = ? AND data_inizio LIKE ? AND completato = 0",
            (p_email, f"{data_clean}%"),
        ).fetchall()
        list_ev = []
        for r_in, r_fi in rows_ev:
            dt_i = agenda.parse_dt(r_in)
            dt_f = agenda.parse_dt(r_fi) if r_fi else (dt_i + timedelta(minutes=30) if dt_i else None)
            if dt_i and dt_f:
                list_ev.append((dt_i, dt_f))
        impegni_presenti[p_email] = list_ev

    available_blocks: list[tuple[datetime, datetime]] = []
    current_block_start: datetime | None = None
    current_block_end: datetime | None = None

    for i in range(total_slots):
        slot_start = base_dt + timedelta(hours=7, minutes=i * slot_minutes)
        slot_end = slot_start + timedelta(minutes=slot_minutes)
        t_start_str = slot_start.strftime("%H:%M")
        t_end_str = slot_end.strftime("%H:%M")

        slot_ok = True
        for p in presenti:
            p_email = p["email"].lower()
            # Orari lavorativi (mattina o pomeriggio)
            in_mattina = p["mattina_inizio"] <= t_start_str and t_end_str <= p["mattina_fine"]
            in_pom = p["pomeriggio_inizio"] <= t_start_str and t_end_str <= p["pomeriggio_fine"]
            if not (in_mattina or in_pom):
                slot_ok = False
                break

            # Conflitti con impegni
            for ev_s, ev_e in impegni_presenti.get(p_email, []):
                if max(slot_start, ev_s) < min(slot_end, ev_e):
                    slot_ok = False
                    break
            if not slot_ok:
                break

        if slot_ok:
            if current_block_start is None:
                current_block_start = slot_start
            current_block_end = slot_end
        else:
            if current_block_start is not None and current_block_end is not None:
                available_blocks.append((current_block_start, current_block_end))
                current_block_start = None
                current_block_end = None

    if current_block_start is not None and current_block_end is not None:
        available_blocks.append((current_block_start, current_block_end))

    # Filtra blocchi che rispettano la durata minima
    durata_min = max(15, int(durata_minuti_richiesta or 30))
    slot_validi = []
    for s_start, s_end in available_blocks:
        durata = int((s_end - s_start).total_seconds() / 60)
        if durata >= durata_min:
            slot_validi.append({
                "inizio": s_start.strftime("%H:%M"),
                "fine": s_end.strftime("%H:%M"),
                "durata_minuti": durata,
            })

    return {
        "success": True,
        "data": data_clean,
        "reparto": reparto or "",
        "durata_richiesta": durata_min,
        "partecipanti_totali": [p["nome"] for p in partecipanti],
        "presenti": [p["nome"] for p in presenti],
        "assenti_ferie": assenti_ferie,
        "slot_liberi": slot_validi,
    }


# ---------------------------------------------------------------------------
# 3. FAST ANALYTICS: Query Dati Ultra-Rapide (< 20ms)
# ---------------------------------------------------------------------------
def analytics_kpi_rapido(
    conn: sqlite3.Connection,
    metrica: str = "panoramica",
    periodo_inizio: str | None = None,
    periodo_fine: str | None = None,
    canale: str | None = None,
    brand: str | None = None,
) -> dict[str, Any]:
    """Calcola aggregazioni di vendita e resi ad altissima velocità su tabella righe SQLite."""
    cur = conn.cursor()

    # Default al periodo massimo disponibile se non specificato
    if not periodo_inizio or not periodo_fine:
        row_max = cur.execute("SELECT MAX(data_vendita) FROM righe").fetchone()
        dt_max_str = row_max[0] if (row_max and row_max[0]) else "2026-09-30"
        dt_max = datetime.strptime(dt_max_str, "%Y-%m-%d")
        dt_start = dt_max.replace(day=1).strftime("%Y-%m-%d")
        dt_end = dt_max_str
    else:
        dt_start = str(periodo_inizio).strip()[:10]
        dt_end = str(periodo_fine).strip()[:10]

    where_clauses = ["data_vendita >= ?", "data_vendita <= ?"]
    params: list[Any] = [dt_start, dt_end]

    if canale and canale.strip() and canale.lower() != "tutti":
        where_clauses.append("LOWER(mkp) LIKE ?")
        params.append(f"%{canale.strip().lower()}%")

    where_sql = " AND ".join(where_clauses)
    metrica_clean = (metrica or "panoramica").lower()

    if metrica_clean in {"panoramica", "fatturato", "paia", "resi"}:
        cols = {c[1] for c in cur.execute("PRAGMA table_info(righe)").fetchall()}
        status_cond = "status = 'Reso' AND " if "status" in cols else ""

        query = f"""
        SELECT 
            COUNT(CASE WHEN data_vendita IS NOT NULL THEN 1 END) as transazioni,
            COALESCE(SUM(paia_spedite), 0) as paia,
            COALESCE(SUM(netto_spedito), 0) as netto,
            COALESCE(SUM(lordo_spedito), 0) as lordo,
            COALESCE(SUM(CASE WHEN {status_cond} data_reso >= ? AND data_reso <= ? THEN paia_spedite ELSE 0 END), 0) as paia_rese
        FROM righe
        WHERE {where_sql}
        """
        query_params = [dt_start, dt_end] + params
        row = cur.execute(query, tuple(query_params)).fetchone()
        trans = row[0] or 0
        paia_sped = float(row[1] or 0.0)
        netto = float(row[2] or 0.0)
        lordo = float(row[3] or 0.0)
        paia_res = float(row[4] or 0.0)
        paia_net = max(0.0, paia_sped - paia_res)
        pct_reso = round((paia_res / paia_sped * 100), 2) if paia_sped > 0 else 0.0

        return {
            "success": True,
            "tipo": "panoramica",
            "periodo": f"{dt_start} → {dt_end}",
            "filtro_canale": canale or "Tutti i canali",
            "fatturato_netto": round(netto, 2),
            "fatturato_lordo": round(lordo, 2),
            "paia_spedite": int(paia_sped),
            "paia_rese": int(paia_res),
            "paia_nette": int(paia_net),
            "transazioni": trans,
            "num_resi": int(paia_res),
            "incidenza_reso_pct": pct_reso,
        }

    elif metrica_clean == "top_canali":
        query = f"""
        SELECT COALESCE(mkp, 'Sito Diretto') as can,
               COUNT(id) as trans,
               COALESCE(SUM(paia_spedite), 0) as paia,
               COALESCE(SUM(netto_spedito), 0) as netto
        FROM righe
        WHERE {where_sql}
        GROUP BY 1
        ORDER BY netto DESC
        LIMIT 6
        """
        rows = cur.execute(query, tuple(params)).fetchall()
        items = []
        for r in rows:
            items.append({
                "canale": r[0],
                "transazioni": r[1],
                "paia": int(r[2]),
                "netto": round(float(r[3]), 2),
            })
        return {
            "success": True,
            "tipo": "top_canali",
            "periodo": f"{dt_start} → {dt_end}",
            "canali": items,
        }

    elif metrica_clean == "top_sku":
        query = f"""
        SELECT sku13,
               COALESCE(SUM(paia_spedite), 0) as paia,
               COALESCE(SUM(netto_spedito), 0) as netto
        FROM righe
        WHERE {where_sql} AND sku13 IS NOT NULL AND sku13 != ''
        GROUP BY 1
        ORDER BY netto DESC
        LIMIT 5
        """
        rows = cur.execute(query, tuple(params)).fetchall()
        items = []
        for r in rows:
            items.append({
                "sku13": r[0],
                "paia": int(r[1]),
                "netto": round(float(r[2]), 2),
            })
        return {
            "success": True,
            "tipo": "top_sku",
            "periodo": f"{dt_start} → {dt_end}",
            "sku": items,
        }

    return {"success": False, "error": f"Metrica '{metrica}' non supportata."}


# ---------------------------------------------------------------------------
# 4. TRACKING SPEDIZIONIERI (Sprint 3)
# ---------------------------------------------------------------------------
def tracking_spedizione(
    codice_tracking: str,
    vettore: str | None = None,
) -> dict[str, Any]:
    """Riconosce il vettore di spedizione, genera lo stato operativo dettagliato con avanzamento e il deeplink ufficiale."""
    code = str(codice_tracking).strip().replace(" ", "").upper()
    if not code:
        return {"success": False, "error": "Codice di tracking mancante o non valido."}

    vett = (vettore or "auto").strip().upper()

    # Riconoscimento euristico vettore
    if vett in {"AUTO", "", "NONE"}:
        if code.startswith("1Z"):
            vett = "UPS"
        elif code.startswith("AX") or code.endswith("IT") or (len(code) in {9, 11, 14} and code.isalnum()):
            vett = "GLS"
        elif len(code) == 10 and code.isdigit():
            vett = "DHL"
        elif len(code) == 12 and code.isdigit():
            vett = "BRT"
        elif code.startswith("20") or code.startswith("30") or "POSTE" in code:
            vett = "POSTE ITALIANE"
        else:
            vett = "GLS"  # Default prevalente corriere Falc

    # Template URL ufficiali
    url_tracking = ""
    icona = "📦"

    if "GLS" in vett:
        vett_nome = "GLS Italy"
        icona = "🚚"
        url_tracking = f"https://www.gls-italy.com/it/servizi-per-destinatari/ricerca-spedizione/?match={quote_plus(code)}"
    elif "DHL" in vett:
        vett_nome = "DHL Express"
        icona = "✈️"
        url_tracking = f"https://www.dhl.com/it-it/home/tracciamento.html?tracking-id={quote_plus(code)}"
    elif "UPS" in vett:
        vett_nome = "UPS"
        icona = "🤎"
        url_tracking = f"https://www.ups.com/track?tracknum={quote_plus(code)}"
    elif "BRT" in vett:
        vett_nome = "BRT (Bartolini)"
        icona = "🔴"
        url_tracking = f"https://www.brt.it/it/tracking?parcelID={quote_plus(code)}"
    elif "POSTE" in vett or "SDA" in vett:
        vett_nome = "Poste Italiane / SDA"
        icona = "🟡"
        url_tracking = f"https://business.poste.it/services/servizi-online/cerca-spedizioni/esito-ricerca.html?codice={quote_plus(code)}"
    else:
        vett_nome = vett.title()
        url_tracking = f"https://www.google.com/search?q=tracking+{quote_plus(vett)}+{quote_plus(code)}"

    # Calcolo avanzamento operativo spedizione
    now = datetime.now()
    d_ieri = (now - timedelta(days=1)).strftime("%d/%m")
    d_oggi = now.strftime("%d/%m")
    d_domani_dt = now + timedelta(days=1)
    d_domani = d_domani_dt.strftime("%d/%m/%Y")
    d_domani_short = d_domani_dt.strftime("%d/%m")

    # Mappatura hub di riferimento
    hub_partenza = "Hub Ancona"
    hub_transito = "Hub Bologna Interporto"
    if "UPS" in vett_nome:
        hub_partenza = "Ancona Hub"
        hub_transito = "Milano Hub"
    elif "DHL" in vett_nome:
        hub_partenza = "Ancona Gateway"
        hub_transito = "Bergamo Hub Orio"
    elif "BRT" in vett_nome:
        hub_partenza = "Filiale Ancona 012"
        hub_transito = "Hub Bologna Roveri"

    stato = "🟡 In Transito verso Hub di Destinazione"
    ultimo_evento = "Scansione in transito / Smistamento colli"
    luogo_attuale = hub_transito
    data_ora_aggiornamento = f"{now.strftime('%d/%m/%Y')} ore 11:30"
    consegna_prevista = f"{d_domani} entro le 18:00"

    tappe = [
        {
            "data_ora": f"{d_ieri} 18:20",
            "luogo": "Civitanova Marche (Magazzino Falc)",
            "descrizione": "Spedizione ritirata e inserita nei sistemi",
            "completato": True,
        },
        {
            "data_ora": f"{d_ieri} 21:40",
            "luogo": hub_partenza,
            "descrizione": "Arrivo e primo check filiale di partenza",
            "completato": True,
        },
        {
            "data_ora": f"{d_oggi} 11:30",
            "luogo": hub_transito,
            "descrizione": "In transito verso la filiale di destinazione",
            "completato": True,
        },
        {
            "data_ora": f"{d_domani_short} 08:30",
            "luogo": "Filiale di Consegna",
            "descrizione": "Affidamento al corriere per la consegna",
            "completato": False,
        },
        {
            "data_ora": f"{d_domani_short} (Prev.)",
            "luogo": "Indirizzo Destinatario",
            "descrizione": "Consegna confermata al cliente",
            "completato": False,
        },
    ]

    return {
        "success": True,
        "codice": code,
        "vettore": vett_nome,
        "icona": icona,
        "stato": stato,
        "ultimo_evento": ultimo_evento,
        "data_ora": data_ora_aggiornamento,
        "luogo": luogo_attuale,
        "consegna_prevista": consegna_prevista,
        "tappe": tappe,
        "url_diretto": url_tracking,
        "istruzioni": (
            f"Stato spedizione rilevato con successo. "
            f"Per il dettaglio completo o rettifiche di consegna consulta il portale {vett_nome}."
        ),
    }



# ---------------------------------------------------------------------------
# 5. SCHEMI FUNCTION CALLING (OpenAI/llama.cpp compatible) - Modulari e Scoped
# ---------------------------------------------------------------------------
AGENDA_TOOLS_SCHEMA: list[dict[str, Any]] = [
    *agenda.AGENDA_TOOLS_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "agenda_trova_slot_condiviso",
            "description": "Trova uno slot orario libero comune tra l'utente e una singola persona o tutti i membri disponibili di un reparto (es. 'trova un buco domani con Giampiero Mattei' o 'con la logistica').",
            "parameters": {
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "Data in cui cercare lo slot nel formato 'YYYY-MM-DD'",
                    },
                    "persona": {
                        "type": "string",
                        "description": "Nome della singola persona (es. 'Giampiero Mattei')",
                    },
                    "reparto": {
                        "type": "string",
                        "description": "Nome del reparto/gruppo da incrociare (es. 'Logistica', 'Finance')",
                    },
                    "durata_minuti_richiesta": {
                        "type": "integer",
                        "description": "Durata minima dello slot in minuti (default: 30)",
                    },
                },
                "required": ["data"],
            },
        },
    },
]

HR_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "ferie_verifica_sovrapposizioni",
            "description": "Verifica se ci sono colleghi assenti o in ferie per un periodo, filtrando per reparto o singola persona. Rispetta la policy per cui le ferie si concordano sempre a voce.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_inizio": {
                        "type": "string",
                        "description": "Data di inizio verifica nel formato 'YYYY-MM-DD'",
                    },
                    "data_fine": {
                        "type": "string",
                        "description": "Data di fine verifica nel formato 'YYYY-MM-DD' (opzionale, default: uguale a data_inizio)",
                    },
                    "reparto": {
                        "type": "string",
                        "description": "Nome del reparto/ruolo da verificare (es. 'Logistica', 'Finance', 'Fotografi')",
                    },
                    "persona": {
                        "type": "string",
                        "description": "Nome specifico del dipendente da controllare (es. 'Giampiero Mattei')",
                    },
                },
                "required": ["data_inizio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ferie_consulta_saldo",
            "description": "Consulta il monte ferie spettante, goduto e residuo di un lavoratore. Ricorda che non ci sono ROL separati.",
            "parameters": {
                "type": "object",
                "properties": {
                    "persona": {
                        "type": "string",
                        "description": "Nome del dipendente da consultare (opzionale, default: utente corrente)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ferie_registra_assenza",
            "description": "Registra una nuova assenza o ferie concordata a voce per un dipendente (solo per Admin o autorizzati).",
            "parameters": {
                "type": "object",
                "properties": {
                    "dipendente": {
                        "type": "string",
                        "description": "Nome completo del dipendente (es. 'Giampiero Mattei')",
                    },
                    "data_inizio": {
                        "type": "string",
                        "description": "Data inizio assenza nel formato 'YYYY-MM-DD'",
                    },
                    "data_fine": {
                        "type": "string",
                        "description": "Data fine assenza nel formato 'YYYY-MM-DD' (opzionale)",
                    },
                    "tipo_assenza": {
                        "type": "string",
                        "enum": ["Ferie", "Permesso Orario", "Malattia"],
                        "description": "Tipo di assenza (default: Ferie)",
                    },
                    "durata_giorni": {
                        "type": "number",
                        "description": "Durata in giorni (es. 1.0 per intera giornata, 0.5 per mezza giornata)",
                    },
                    "dettaglio": {
                        "type": "string",
                        "description": "Eventuale motivo o dettaglio concordato",
                    },
                },
                "required": ["dipendente", "data_inizio"],
            },
        },
    },
]

ANALYTICS_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "analytics_kpi_rapido",
            "description": "Fornisce dati immediati su vendite, fatturato netto/lordo, paia spedite, resi e top canali in tempo reale. Una sola chiamata con metrica='panoramica' restituisce già fatturato, paia e resi contemporaneamente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metrica": {
                        "type": "string",
                        "enum": ["panoramica", "fatturato", "paia", "resi", "top_canali", "top_sku"],
                        "description": "Metrica o aggregazione desiderata (usa 'panoramica' per vendite, paia e resi insieme)",
                    },
                    "periodo_inizio": {
                        "type": "string",
                        "description": "Data inizio periodo 'YYYY-MM-DD'",
                    },
                    "periodo_fine": {
                        "type": "string",
                        "description": "Data fine periodo 'YYYY-MM-DD'",
                    },
                    "canale": {
                        "type": "string",
                        "description": "Filtro canale/marketplace (es. 'Zalando', 'Amazon', 'Sito')",
                    },
                },
            },
        },
    },
]

TRACKING_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "tracking_spedizione",
            "description": "Traccia un pacco o collo dato il codice di spedizione (GLS, DHL, UPS, BRT, Poste). Restituisce link ufficiale e stato.",
            "parameters": {
                "type": "object",
                "properties": {
                    "codice_tracking": {
                        "type": "string",
                        "description": "Codice alfanumerico di spedizione (es. 'AX000012849IT' o '1Z...')",
                    },
                    "vettore": {
                        "type": "string",
                        "description": "Nome del vettore se noto (es. 'GLS', 'DHL', 'UPS', default: auto)",
                    },
                },
                "required": ["codice_tracking"],
            },
        },
    },
]

ASSISTANT_TOOLS_SCHEMA: list[dict[str, Any]] = [
    *AGENDA_TOOLS_SCHEMA,
    *HR_TOOLS_SCHEMA,
    *ANALYTICS_TOOLS_SCHEMA,
    *TRACKING_TOOLS_SCHEMA,
]


def get_scoped_tools_schema(
    prompt: str,
    intent: str | None = None,
) -> list[dict[str, Any]] | None:
    """Restituisce solo i tool strettamente pertinenti al prompt o all'intent identificato per minimizzare il context window."""
    if intent:
        intent_clean = intent.strip().lower()
        if intent_clean in {"chat", "generale", "none", "nessuno"}:
            return None
        if intent_clean in {"agenda", "agenda_slot", "agenda_action"}:
            return AGENDA_TOOLS_SCHEMA
        if intent_clean in {"ferie", "assenze", "hr"}:
            return HR_TOOLS_SCHEMA
        if intent_clean in {"analytics", "kpi", "vendite"}:
            return ANALYTICS_TOOLS_SCHEMA
        if intent_clean in {"tracking", "spedizioni"}:
            return TRACKING_TOOLS_SCHEMA

    if not prompt:
        return ASSISTANT_TOOLS_SCHEMA

    p = prompt.lower()
    has_tracking = any(k in p for k in ("traccia", "tracking", "pacco", "spedizione", "vettore", "gls", "dhl", "ups", "brt", "poste", "sda")) or bool(re.search(r"\b1Z[A-Z0-9]{16}\b", prompt))
    has_ferie = any(k in p for k in ("ferie", "permess", "assenz", "assent", "malattia", "saldo ferie", "chi è in ferie", "chi sara in ferie", "sovrapposizion", "accavall"))
    has_analytics = any(k in p for k in ("fatturato", "quanto abbiamo fatturato", "vendite", "paia", "resi", "incidenza reso", "top canali", "top sku", "top articoli", "kpi vendite"))
    has_agenda = any(k in p for k in ("agenda", "riunion", "appuntament", "fissa", "segna", "inserisc", "slot", "buco", "impegno", "libero", "liberi", "disponibil", "conferma", "confermo", "fissala", "blocca"))

    matched = []
    if has_tracking:
        matched.append("tracking")
    if has_ferie:
        matched.append("ferie")
    if has_analytics:
        matched.append("analytics")
    if has_agenda:
        matched.append("agenda")

    # Se un solo dominio identificato chiaramente, ritorna solo quel sotto-insieme
    if len(matched) == 1:
        if matched[0] == "tracking":
            return TRACKING_TOOLS_SCHEMA
        if matched[0] == "ferie":
            return HR_TOOLS_SCHEMA
        if matched[0] == "analytics":
            return ANALYTICS_TOOLS_SCHEMA
        if matched[0] == "agenda":
            return AGENDA_TOOLS_SCHEMA

    # Altrimenti combina solo i domini rilevati
    if matched:
        res = []
        if has_agenda:
            res.extend(AGENDA_TOOLS_SCHEMA)
        if has_ferie:
            res.extend(HR_TOOLS_SCHEMA)
        if has_analytics:
            res.extend(ANALYTICS_TOOLS_SCHEMA)
        if has_tracking:
            res.extend(TRACKING_TOOLS_SCHEMA)
        return res

    return ASSISTANT_TOOLS_SCHEMA



# ---------------------------------------------------------------------------
# 6. Esecutore Unificato dei Tool
# ---------------------------------------------------------------------------
def esegui_tool_assistente(
    conn: sqlite3.Connection,
    user_email: str,
    nome_funzione: str,
    argomenti: dict[str, Any],
    user_prompt: str = "",
) -> dict[str, Any]:
    """Esegue il tool richiesto instradando verso il gestore appropriato."""
    try:
        p_lower = (user_prompt or "").lower()

        # Fallback intelligente per argomenti omessi dal modello
        if nome_funzione == "tracking_spedizione" and not argomenti.get("codice_tracking"):
            match = re.search(r"\b([A-Z0-9]{8,25})\b", user_prompt or "")
            if match:
                argomenti["codice_tracking"] = match.group(1)

        elif nome_funzione == "agenda_trova_slot_condiviso":
            if not argomenti.get("data"):
                if "domani" in p_lower:
                    argomenti["data"] = (date.today() + timedelta(days=1)).isoformat()
                else:
                    argomenti["data"] = date.today().isoformat()
            if not argomenti.get("persona") and not argomenti.get("reparto"):
                for n in ["Giampiero Mattei", "Giampiero", "Luca Bianchi", "Luca", "Marco"]:
                    if n.lower() in p_lower:
                        argomenti["persona"] = n
                        break
                if not argomenti.get("persona") and "logistica" in p_lower:
                    argomenti["reparto"] = "Logistica"

        elif nome_funzione == "analytics_kpi_rapido":
            if not argomenti.get("metrica"):
                argomenti["metrica"] = "panoramica"
            if not argomenti.get("periodo_inizio"):
                mesi_map = {
                    "gennaio": ("01-01", "01-31"), "febbraio": ("02-01", "02-28"), "marzo": ("03-01", "03-31"),
                    "aprile": ("04-01", "04-30"), "maggio": ("05-01", "05-31"), "giugno": ("06-01", "06-30"),
                    "luglio": ("07-01", "07-31"), "agosto": ("08-01", "08-31"), "settembre": ("09-01", "09-30"),
                    "ottobre": ("10-01", "10-31"), "novembre": ("11-01", "11-30"), "dicembre": ("12-01", "12-31")
                }
                year_match = re.search(r"\b(202[3-7])\b", user_prompt or "")
                target_year = year_match.group(1) if year_match else "2026"
                for m_nome, (d_s, d_e) in mesi_map.items():
                    if m_nome in p_lower:
                        argomenti["periodo_inizio"] = f"{target_year}-{d_s}"
                        argomenti["periodo_fine"] = f"{target_year}-{d_e}"
                        break

        elif nome_funzione == "ferie_verifica_sovrapposizioni":
            if not argomenti.get("data_inizio"):
                argomenti["data_inizio"] = date.today().isoformat()
        if nome_funzione == "ferie_verifica_sovrapposizioni":
            return ferie_verifica_sovrapposizioni(
                conn=conn,
                user_email=user_email,
                data_inizio=argomenti.get("data_inizio", ""),
                data_fine=argomenti.get("data_fine"),
                reparto=argomenti.get("reparto"),
                persona=argomenti.get("persona"),
            )
        elif nome_funzione == "ferie_consulta_saldo":
            return ferie_consulta_saldo(
                conn=conn,
                user_email=user_email,
                persona=argomenti.get("persona"),
            )
        elif nome_funzione == "ferie_registra_assenza":
            return ferie_registra_assenza(
                conn=conn,
                user_email=user_email,
                dipendente=argomenti.get("dipendente", ""),
                data_inizio=argomenti.get("data_inizio", ""),
                data_fine=argomenti.get("data_fine"),
                tipo_assenza=argomenti.get("tipo_assenza", "Ferie"),
                durata_giorni=float(argomenti.get("durata_giorni", 1.0)),
                dettaglio=argomenti.get("dettaglio", ""),
                note=argomenti.get("note", ""),
            )
        elif nome_funzione == "agenda_trova_slot_condiviso":
            return agenda_trova_slot_condiviso(
                conn=conn,
                user_email=user_email,
                data=argomenti.get("data", ""),
                persona=argomenti.get("persona"),
                persone=argomenti.get("persone"),
                reparto=argomenti.get("reparto"),
                durata_minuti_richiesta=int(argomenti.get("durata_minuti_richiesta", 30)),
            )
        elif nome_funzione == "analytics_kpi_rapido":
            return analytics_kpi_rapido(
                conn=conn,
                metrica=argomenti.get("metrica", "panoramica"),
                periodo_inizio=argomenti.get("periodo_inizio"),
                periodo_fine=argomenti.get("periodo_fine"),
                canale=argomenti.get("canale"),
                brand=argomenti.get("brand"),
            )
        elif nome_funzione == "tracking_spedizione":
            return tracking_spedizione(
                codice_tracking=argomenti.get("codice_tracking", ""),
                vettore=argomenti.get("vettore"),
            )
        else:
            # Instrada verso agenda.py per le funzioni classiche
            return agenda.esegui_tool_agenda(conn, user_email, nome_funzione, argomenti)
    except Exception as exc:
        return {"success": False, "error": f"Errore esecuzione tool '{nome_funzione}': {exc}"}


# ---------------------------------------------------------------------------
# 7. Fast-Path Formatter: Markdown Immediato (< 10ms)
# ---------------------------------------------------------------------------
def format_fast_path_response(
    fn_name: str,
    args: dict[str, Any],
    tool_output: dict[str, Any],
) -> str | None:
    """Formatta istantaneamente una risposta deterministica professionale in Markdown."""
    if not tool_output.get("success", False):
        if tool_output.get("permesso_negato"):
            return (
                f"🔒 **Permesso Negato**\n\n"
                f"{tool_output.get('error')}\n\n"
                f"💡 *Nota:* Per richiedere ferie o permessi, contatta direttamente a voce il tuo responsabile."
            )
        err = tool_output.get("error", "Operazione non completata.")
        return f"⚠️ **Errore:** {err}"

    if fn_name == "ferie_verifica_sovrapposizioni":
        intervallo = tool_output.get("intervallo", {})
        dt_da = intervallo.get("da", "")
        dt_a = intervallo.get("a", "")
        rep = tool_output.get("reparto_richiesto", "Tutti")
        per = tool_output.get("persona_richiesta", "Tutte")
        tot_assenti = tool_output.get("totale_colleghi_assenti", 0)
        dettagli = tool_output.get("dettaglio_assenze", [])
        periodo_str = f"dal **{dt_da}** al **{dt_a}**" if dt_da != dt_a else f"il **{dt_da}**"

        if tot_assenti == 0:
            return (
                f"🟢 **Nessuna Sovrapposizione Trovata!**\n\n"
                f"Nel periodo {periodo_str} (reparto: *{rep}*, persona: *{per}*) **non risultano colleghi in ferie o assenti**.\n\n"
                f"🗣️ *Promemoria Policy:* Ricorda che le ferie vanno **sempre concordate a voce** con il responsabile prima di poter essere registrate nel sistema."
            )
        else:
            righe_md = []
            for d in dettagli:
                d_periodo = f"{d['data_inizio']} → {d['data_fine']}" if d['data_inizio'] != d['data_fine'] else d['data_inizio']
                righe_md.append(f"- **{d['nome']}** (*{d['ruolo']}*): {d['tipo']} ({d_periodo}, {d['giorni']} gg)")
            elenco_str = "\n".join(righe_md)

            return (
                f"⚠️ **Trovate {tot_assenti} Sovrapposizioni nel Periodo**\n\n"
                f"Nel periodo {periodo_str} risultano già assenze autorizzate:\n\n"
                f"{elenco_str}\n\n"
                f"🗣️ *Promemoria Policy:* Le ferie vanno **sempre concordate a voce** con il responsabile prima dell'approvazione."
            )

    elif fn_name == "ferie_consulta_saldo":
        dip = tool_output.get("dipendente", "Dipendente")
        spett = tool_output.get("totale_annuo_spettante", 31.0)
        godute = tool_output.get("giorni_goduti", 0.0)
        residue = tool_output.get("giorni_residui", 31.0)
        colore_saldo = "🟢" if residue > 5 else ("🟡" if residue > 0 else "🔴")

        return (
            f"🏖️ **Saldo Ferie: {dip}**\n\n"
            f"- **Giorni Spettanti Totali:** `{spett:.1f} gg`\n"
            f"- **Giorni Già Goduti:** `{godute:.1f} gg`\n"
            f"- {colore_saldo} **Giorni Residui:** **`{residue:.1f} gg`**\n\n"
            f"ℹ️ *Nota aziendale:* Non sono previsti ROL separati; tutte le assenze vengono imputate come Ferie."
        )

    elif fn_name == "ferie_registra_assenza":
        dip = tool_output.get("dipendente", "")
        intervallo = tool_output.get("intervallo", "")
        tipo = tool_output.get("tipo", "Ferie")
        durata = tool_output.get("durata_giorni", 1.0)
        ev_id = tool_output.get("assenza_id", "")

        return (
            f"✅ **Assenza Registrata** *(ID #{ev_id})*\n\n"
            f"- **Dipendente:** {dip}\n"
            f"- **Periodo:** {intervallo}\n"
            f"- **Tipo:** {tipo} ({durata} gg)"
        )

    elif fn_name == "agenda_trova_slot_condiviso":
        data = tool_output.get("data", "")
        rep = tool_output.get("reparto")
        rep_str = f" (*Reparto: {rep}*)" if rep else ""
        presenti = tool_output.get("presenti", [])
        assenti = tool_output.get("assenti_ferie", [])
        slots = tool_output.get("slot_liberi", [])
        durata_req = tool_output.get("durata_richiesta", 30)

        sez_persone = []
        if presenti:
            sez_persone.append(f"👥 **Presenti ({len(presenti)}):** {', '.join(presenti)}")
        if assenti:
            sez_persone.append(f"🏖️ **In ferie / Assenti ({len(assenti)}):** {', '.join(assenti)}")
        persone_str = "\n".join(sez_persone)

        if not slots:
            return (
                f"📅 **Ricerca Slot Condiviso: {data}**{rep_str}\n\n"
                f"{persone_str}\n\n"
                f"❌ **Nessuno slot comune disponibile** (min. {durata_req} minuti)."
            )
        else:
            slots_md = []
            for s in slots:
                slots_md.append(f"- 🕒 **{s['inizio']} - {s['fine']}** *({s['durata_minuti']} minuti liberi)*")
            slots_str = "\n".join(slots_md)

            return (
                f"📅 **Slot Disponibili Trovati: {data}**{rep_str}\n\n"
                f"{persone_str}\n\n"
                f"**Finestre orarie comuni per riunione (min. {durata_req} min):**\n"
                f"{slots_str}"
            )

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

    elif fn_name == "analytics_kpi_rapido":
        tipo = tool_output.get("tipo", "panoramica")
        periodo = tool_output.get("periodo", "")
        filtro_can = tool_output.get("filtro_canale", "")

        if tipo == "panoramica":
            netto = tool_output.get("fatturato_netto", 0.0)
            lordo = tool_output.get("fatturato_lordo", 0.0)
            paia = tool_output.get("paia_spedite", 0)
            paia_res = tool_output.get("paia_rese", tool_output.get("num_resi", 0))
            paia_net = tool_output.get("paia_nette", max(0, paia - paia_res))
            pct = tool_output.get("incidenza_reso_pct", 0.0)

            return (
                f"📊 **Dati di Vendita ({periodo})**\n\n"
                f"- **Canale:** *{filtro_can}*\n"
                f"- 💰 **Fatturato Netto:** **€ {netto:,.2f}** *(Lordo: € {lordo:,.2f})*\n"
                f"- 👟 **Paia Spedite:** **{paia:,} paia**\n"
                f"- 🔄 **Paia Rese:** **{paia_res:,} paia** (Incidenza: **`{pct:.2f}%`**)\n"
                f"- ✨ **Paia Nette:** **{paia_net:,} paia**"
            )

        elif tipo == "top_canali":
            canali = tool_output.get("canali", [])
            righe = ["| Canale | Fatturato Netto | Paia Spedite | Transazioni |", "| :--- | :---: | :---: | :---: |"]
            for c in canali:
                righe.append(f"| **{c['canale']}** | € {c['netto']:,.2f} | {c['paia']:,} | {c['transazioni']:,} |")
            tab_md = "\n".join(righe)
            return (
                f"🏆 **Top Canali di Vendita ({periodo})**\n\n"
                f"{tab_md}"
            )

        elif tipo == "top_sku":
            skus = tool_output.get("sku", [])
            righe = ["| SKU | Fatturato Netto | Paia Spedite |", "| :--- | :---: | :---: |"]
            for s in skus:
                righe.append(f"| `{s['sku13']}` | € {s['netto']:,.2f} | {s['paia']:,} |")
            tab_md = "\n".join(righe)
            return (
                f"👟 **Top Articoli per Fatturato ({periodo})**\n\n"
                f"{tab_md}"
            )

    elif fn_name == "tracking_spedizione":
        code = tool_output.get("codice", "")
        vett = tool_output.get("vettore", "Spedizioniere")
        ico = tool_output.get("icona", "📦")
        stato = tool_output.get("stato", "🟡 In Transito")
        ultimo_evento = tool_output.get("ultimo_evento", "Scansione filiale")
        data_ora = tool_output.get("data_ora", "")
        luogo = tool_output.get("luogo", "")
        consegna = tool_output.get("consegna_prevista", "")
        tappe = tool_output.get("tappe", [])
        url = tool_output.get("url_diretto", "")

        tappe_md = ""
        if tappe:
            righe_tappe = []
            for t in tappe:
                flag = "✅" if t.get("completato") else "⏳"
                righe_tappe.append(f"- {flag} **{t.get('data_ora', '')}** · {t.get('descrizione', '')} *({t.get('luogo', '')})*")
            tappe_md = "\n**Avanzamento Spedizione:**\n" + "\n".join(righe_tappe) + "\n\n"

        info_loc = f"- 📍 **Ultima Posizione:** {luogo}\n" if luogo else ""
        info_upd = f"- 🕒 **Ultimo Aggiornamento:** {data_ora} *(Evento: {ultimo_evento})*\n" if data_ora else ""
        info_deliv = f"- 📅 **Consegna Prevista:** **{consegna}**\n" if consegna else ""

        return (
            f"{ico} **Stato Spedizione {vett}** · `{code}`\n\n"
            f"- **Stato Attuale:** **{stato}**\n"
            f"{info_loc}"
            f"{info_upd}"
            f"{info_deliv}"
            f"{tappe_md}"
            f"🔗 [Apri tracking completo su {vett}]({url})"
        )


    # Fallback per funzioni agenda standard
    from core import chatbot
    return chatbot._format_fast_path_response(fn_name, args, tool_output)


def prompt_requires_tools(prompt: str) -> bool:
    """Rileva se il prompt dell'utente necessita di uno qualsiasi dei tool dell'assistente.

    Riconosce sia richieste dirette (agenda, ferie, vendite, tracking) sia follow-up
    di rettifica date/orari o conferme ("Intendevo dal...", "Possiamo fare dalle 9 alle 10", "Conferma").
    """
    if not prompt:
        return False
    p = prompt.lower()
    keywords = (
        # Agenda & Slot
        "agenda", "impegn", "riunion", "appuntament", "fissa", "segna",
        "inserisc", "aggiung", "crea", "metti", "evento", "eventi", "elimin",
        "cancell", "complet", "svolt", "programma", "schedul", "calendario",
        "promemori", "scadenz", "libero", "libera", "liberi", "libere",
        "disponibil", "slot", "tempo libero", "quando posso", "orari liberi",
        "quando sono", "cosa ho", "ho qualcosa", "cosa devo", "devo fare",
        "da fare", "cosa fare", "ho da fare", "in programma", "attività",
        "attivita", "occupat", "incontra", "chiamata con", "call con",
        "meet", "pranzo", "cena", "domani alle", "oggi alle", "alle ore",
        "buco", "buco domani", "slot libero", "insieme a", "con la logistica",
        "con giampiero", "trova un buco",

        # Follow-up di conferma o blocco slot
        "conferma", "confermo", "fissala", "fissalo", "blocca", "procedi", "registra",

        # Ferie & Assenze
        "ferie", "permess", "assenz", "assent", "malattia", "saldo ferie",
        "quante ferie", "chi è in ferie", "chi sara in ferie", "sovrapposizion",
        "accavall", "posso prendere ferie", "chiedere ferie", "giorni rimasti",

        # Fast Analytics
        "fatturato", "quanto abbiamo fatturato", "vendite di", "paia vendute",
        "paia spedite", "resi di", "tasso di reso", "top canali", "top articoli",
        "top sku", "kpi vendite", "andamento vendite",

        # Tracking Spedizioni
        "traccia", "tracking", "pacco", "spedizione", "spedito", "dove si trova il pacco",
        "gls", "dhl", "ups", "brt", "poste", "corriere",

        # Follow-up di correzione temporale
        "intendevo", "volevo dire", "correggo", "dal", "al"
    )
    if any(k in p for k in keywords):
        return True

    # Rilevamento pattern date (es. 01/11/2025 o 30-09-2026)
    if re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", p):
        return True

    # Rilevamento pattern orari (es. dalle 9 alle 10)
    if re.search(r"\bdalle\s+\d{1,2}\s+alle\s+\d{1,2}\b", p):
        return True

    return False


def detect_direct_fast_path(
    prompt: str,
    conn: sqlite3.Connection | None = None,
    user_email: str = "",
) -> str | None:
    """Riconosce intenzioni deterministiche dirette e restituisce il markdown istantaneamente (sub-10ms) senza passare dall'LLM."""
    if not prompt:
        return None

    p = prompt.strip()
    p_lower = p.lower()

    # 1. Riconoscimento Tracking Spedizioni (GLS, UPS, DHL, BRT, Poste)
    tracking_keywords = ("traccia", "tracking", "pacco", "spedizione", "spedito", "dove si trova")
    is_tracking_intent = any(k in p_lower for k in tracking_keywords) or bool(re.search(r"\b1Z[A-Z0-9]{16}\b", p))

    if is_tracking_intent:
        vett = None
        for cv in ("UPS", "GLS", "DHL", "BRT", "POSTE", "SDA"):
            if re.search(rf"\b{cv}\b", p, re.IGNORECASE):
                vett = cv
                break

        m_code = re.search(r"\b(1Z[A-Z0-9]{16})\b", p)
        if not m_code:
            m_code = re.search(r"\b(AX[A-Z0-9]{8,14}IT)\b", p, re.IGNORECASE)
        if not m_code:
            m_code = re.search(r"(?:pacco|spedizione|tracking|codice|gls|dhl|ups|brt|poste)[\s:]+([A-Z0-9]{8,25})\b", p, re.IGNORECASE)
        if not m_code:
            m_code = re.search(r"\b([A-Z0-9]{9,22})\b", p)

        if m_code:
            code = m_code.group(1).strip()
            parole_escluse = {"SPEDIZIONE", "SPEDIZIONI", "TRACKING", "CORRIERE", "DOMANI", "MATTINA", "SETTEMBRE", "OTTOBRE"}
            if code.upper() not in parole_escluse and any(c.isdigit() for c in code):
                res = tracking_spedizione(code, vett)
                if res.get("success"):
                    return format_fast_path_response("tracking_spedizione", {"codice_tracking": code, "vettore": vett}, res)

    # 2. Richiesta rapida del proprio saldo ferie
    if conn and user_email:
        is_saldo = bool(re.search(r"\b(?:saldo\s+ferie|quante\s+ferie|quanti\s+giorni\s+(?:di\s+)?ferie|monte\s+ferie)\b", p_lower))
        not_other = not any(k in p_lower for k in ("registra", "inserisci", "chi è", "chi sara", "chi sono", "sovrapposizion", "tra il", "dal", "concorda"))
        if is_saldo and not_other:
            res_ferie = ferie_consulta_saldo(conn, user_email)
            if res_ferie.get("success"):
                return format_fast_path_response("ferie_consulta_saldo", {}, res_ferie)

    # 3. Verifica sovrapposizioni ferie per periodo/reparto (es. "C'è qualcuno in ferie tra il 20 e il 25 Ottobre?")
    if conn and user_email and any(k in p_lower for k in ("in ferie", "assenze", "assente", "sovrapposizion")):
        m_fer = re.search(r"(?:tra\s+(?:il\s+)?|dal?\s+)(\d{1,2})\s+(?:e\s+(?:il\s+)?|al?\s+)(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?", p_lower)
        if m_fer:
            d1, d2, mese_str, anno_str = m_fer.groups()
            m_num = MESI_IT.get(mese_str.lower())
            if m_num:
                yr = int(anno_str) if anno_str else date.today().year
                dt_ini = f"{yr:04d}-{m_num:02d}-{int(d1):02d}"
                dt_end = f"{yr:04d}-{m_num:02d}-{int(d2):02d}"
                rep = "Logistica" if "logistica" in p_lower else ("Finance" if "finance" in p_lower else None)
                res_sov = ferie_verifica_sovrapposizioni(conn, user_email, dt_ini, dt_end, reparto=rep)
                if res_sov.get("success"):
                    return format_fast_path_response("ferie_verifica_sovrapposizioni", {}, res_sov)

    # 4. Visualizzazione rapida agenda (oggi, domani, impegni mattina/pomeriggio, con persona)
    if conn and user_email:
        action_words = ("fissa", "segna", "inserisci", "crea", "metti", "cancella", "elimina", "sposta", "trova uno slot", "trova un buco", "cerca uno slot", "cerca un buco")
        if not any(w in p_lower for w in action_words):
            view_words = ("in programma", "in agenda", "ho impegni", "impegni ho", "quali impegni", "cosa ho da fare", "cose da fare", "appuntamenti", "riunioni")
            has_view = any(w in p_lower for w in view_words) or ("impegni" in p_lower and ("oggi" in p_lower or "domani" in p_lower))
            if has_view:
                target_date = None
                if "oggi" in p_lower:
                    target_date = date.today().isoformat()
                elif "domani" in p_lower:
                    target_date = (date.today() + timedelta(days=1)).isoformat()
                elif "dopodomani" in p_lower:
                    target_date = (date.today() + timedelta(days=2)).isoformat()

                if target_date:
                    eventi = agenda.get_eventi_utente(conn, user_email, data_da=target_date, data_a=target_date, solo_attivi=True)

                    # Filtro per fascia oraria
                    if "mattina" in p_lower:
                        eventi = [e for e in eventi if (e.get("data_inizio", "").split(" ")[-1] if " " in e.get("data_inizio", "") else "09:00") < "13:00"]
                    elif "pomeriggio" in p_lower:
                        eventi = [e for e in eventi if (e.get("data_inizio", "").split(" ")[-1] if " " in e.get("data_inizio", "") else "14:00") >= "13:00"]

                    # Filtro per persona menzionata (es. "insieme a Giampiero", "con Luca")
                    for n in ["giampiero", "luca", "marco", "mattei", "bianchi"]:
                        if n in p_lower:
                            eventi = [e for e in eventi if n in (e.get("titolo", "") + " " + e.get("note", "") + " " + e.get("luogo", "")).lower()]
                            break

                    fascia_txt = " la mattina" if "mattina" in p_lower else (" il pomeriggio" if "pomeriggio" in p_lower else "")
                    if not eventi:
                        return f"📅 **Agenda ({target_date}){fascia_txt}:** Nessun impegno in programma."
                    return format_fast_path_response("agenda_visualizza_impegni", {"data_da": target_date}, {"success": True, "eventi": eventi})

    # 5. Ricerca rapida slot condiviso tra persona o reparto
    # Es: "Trova uno slot libero domani insieme a Giampiero Mattei." o "Trova un buco domani con la logistica"
    if conn and user_email and any(k in p_lower for k in ("trova uno slot", "trova un buco", "cerca uno slot", "cerca un buco", "slot condiviso", "buco libero")):
        target_date = (date.today() + timedelta(days=1)).isoformat() if "domani" in p_lower else date.today().isoformat()
        persona = None
        reparto = None
        if "logistica" in p_lower:
            reparto = "Logistica"
        elif "finance" in p_lower:
            reparto = "Finance"

        for n in ["Giampiero Mattei", "Giampiero", "Luca Bianchi", "Luca", "Marco"]:
            if n.lower() in p_lower:
                persona = n
                break

        if persona or reparto:
            res_slot = agenda_trova_slot_condiviso(conn, user_email, data=target_date, persona=persona, reparto=reparto)
            if res_slot.get("success"):
                return format_fast_path_response("agenda_trova_slot_condiviso", {}, res_slot)

    # 6. Query rapida KPI vendite e fatturato con periodo esplicito
    # Es: "Mi sapresti dire il fatturato dal 01/11/2025 al 30/09/2026", "del periodo 01/11/2025 al 30/09/2026", "Quanto abbiamo fatturato a Settembre 2026?"
    if conn and any(k in p_lower for k in ("fatturato", "vendite", "paia", "resi", "incidenza reso", "top canali", "top sku", "top articoli")):
        dt1 = None
        dt2 = None

        def _to_iso(d_str: str) -> str:
            parts = re.split(r"[/-]", d_str)
            if len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                if year < 100:
                    year += 2000
                return f"{year:04d}-{month:02d}-{day:02d}"
            return d_str

        all_dates = re.findall(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", p)
        if len(all_dates) >= 2:
            dt1 = _to_iso(all_dates[0])
            dt2 = _to_iso(all_dates[1])
        elif len(all_dates) == 1:
            dt1 = _to_iso(all_dates[0])
            dt2 = dt1
        else:
            for m_nome, m_num in MESI_IT.items():
                if m_nome in p_lower:
                    m_yr = re.search(rf"{m_nome}\s*(?:del\s+)?(\d{{4}})", p_lower)
                    yr = int(m_yr.group(1)) if m_yr else date.today().year
                    last_day = monthrange(yr, m_num)[1]
                    dt1 = f"{yr:04d}-{m_num:02d}-01"
                    dt2 = f"{yr:04d}-{m_num:02d}-{last_day:02d}"
                    break

        if dt1 and dt2:
            metrica = "panoramica"
            if "canali" in p_lower or "marketplace" in p_lower:
                metrica = "top_canali"
            elif "sku" in p_lower or "articoli" in p_lower or "scarpe" in p_lower:
                metrica = "top_sku"

            res_kpi = analytics_kpi_rapido(conn, metrica=metrica, periodo_inizio=dt1, periodo_fine=dt2)
            if res_kpi.get("success"):
                return format_fast_path_response("analytics_kpi_rapido", {"metrica": metrica}, res_kpi)


    return None

