"""
Modulo Gestione Ferie e Permessi per EcomAnalysis.
Persistenza completa su database locale SQLite (tabelle `dipendenti` e `ferie_assenze`).
"""
from __future__ import annotations

import calendar as _calendar_mod
import hashlib
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import holidays
import pandas as pd
import streamlit as st

# Palette colori stabile per dipendente
_PALETTE_CALENDARIO = [
    "#0D9488", "#0284C7", "#6366F1", "#8B5CF6", "#EC4899",
    "#F59E0B", "#10B981", "#3B82F6", "#D97706", "#64748B"
]

_GIORNI_IT = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
_MESI_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
MESI_IT_LUNGO = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]

ORARIO_DEFAULT = {
    "mattina_inizio": "08:00",
    "mattina_fine": "12:00",
    "pomeriggio_inizio": "14:00",
    "pomeriggio_fine": "18:00",
}
_DATA_RIF_ORARIO = date(2000, 1, 1)


DEFAULT_BUDGET_ANNUO = 31.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_ferie_tables(conn: sqlite3.Connection) -> None:
    """Crea le tabelle dipendenti, ferie_assenze e ferie_config nel DB SQLite se non esistono."""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS dipendenti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL,
        email TEXT DEFAULT '',
        totale_annuo REAL NOT NULL DEFAULT 31.0,
        mattina_inizio TEXT NOT NULL DEFAULT '08:00',
        mattina_fine TEXT NOT NULL DEFAULT '12:00',
        pomeriggio_inizio TEXT NOT NULL DEFAULT '14:00',
        pomeriggio_fine TEXT NOT NULL DEFAULT '18:00',
        attivo INTEGER NOT NULL DEFAULT 1,
        creato_il TEXT NOT NULL,
        aggiornato_il TEXT NOT NULL
    );
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ferie_assenze (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        data_inizio TEXT NOT NULL,
        data_fine TEXT NOT NULL,
        tipo TEXT NOT NULL DEFAULT 'Ferie',
        giorni_lavorativi REAL NOT NULL,
        dettaglio TEXT DEFAULT '',
        note TEXT DEFAULT '',
        creato_il TEXT NOT NULL
    );
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ferie_config (
        chiave TEXT PRIMARY KEY,
        valore TEXT NOT NULL,
        aggiornato_il TEXT NOT NULL
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ferie_nome ON ferie_assenze(nome);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ferie_date ON ferie_assenze(data_inizio, data_fine);")

    # Inizializza il budget annuo predefinito se non presente
    now = _now_iso()
    conn.execute("""
    INSERT OR IGNORE INTO ferie_config (chiave, valore, aggiornato_il)
    VALUES ('budget_annuo_default', ?, ?)
    """, (str(DEFAULT_BUDGET_ANNUO), now))

    conn.commit()
    sync_utenti_con_dipendenti(conn)


def get_budget_annuo_default(conn: sqlite3.Connection) -> float:
    """Recupera il budget annuo predefinito configurato per i dipendenti."""
    try:
        row = conn.execute("SELECT valore FROM ferie_config WHERE chiave = 'budget_annuo_default'").fetchone()
        if row and row[0]:
            return float(row[0])
    except Exception:
        pass
    return DEFAULT_BUDGET_ANNUO


def set_budget_annuo_default(conn: sqlite3.Connection, budget: float) -> bool:
    """Salva il nuovo budget annuo predefinito nella configurazione persistente."""
    now = _now_iso()
    try:
        conn.execute("""
        INSERT INTO ferie_config (chiave, valore, aggiornato_il)
        VALUES ('budget_annuo_default', ?, ?)
        ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore, aggiornato_il = excluded.aggiornato_il
        """, (str(float(budget)), now))
        conn.commit()
        return True
    except Exception:
        return False


def applica_budget_a_tutti_i_dipendenti(conn: sqlite3.Connection, nuovo_budget: float) -> tuple[bool, int]:
    """Aggiorna il budget annuo di tutti i dipendenti attivi."""
    now = _now_iso()
    try:
        cur = conn.execute(
            "UPDATE dipendenti SET totale_annuo = ?, aggiornato_il = ? WHERE attivo = 1",
            (float(nuovo_budget), now)
        )
        conn.commit()
        return True, cur.rowcount
    except Exception as e:
        return False, 0


def nome_da_email(email: str) -> str:
    """Ricava un nome leggibile da un indirizzo email aziendale (es. mario.rossi@azienda.com -> 'Mario Rossi')."""
    raw = (email or "").strip()
    if not raw or "@" not in raw:
        return raw or "Dipendente"
    local = raw.split("@")[0]
    import re
    parts = [p.capitalize() for p in re.split(r"[._\-+]", local) if p]
    return " ".join(parts) if parts else local.capitalize()


def sync_utenti_con_dipendenti(conn: sqlite3.Connection) -> int:
    """Sincronizza automaticamente gli utenti registrati nel sistema nella tabella dipendenti."""
    try:
        utenti_rows = conn.execute("SELECT email FROM utenti_ruoli").fetchall()
    except Exception:
        return 0

    if not utenti_rows:
        return 0

    aggiunti = 0
    now = _now_iso()
    for row in utenti_rows:
        email = (row[0] or "").strip().lower()
        if not email:
            continue

        esiste = conn.execute(
            "SELECT 1 FROM dipendenti WHERE lower(email) = ?", (email,)
        ).fetchone()
        if esiste:
            continue

        nome_base = nome_da_email(email)
        nome_candidato = nome_base
        counter = 2
        while conn.execute("SELECT 1 FROM dipendenti WHERE nome = ?", (nome_candidato,)).fetchone():
            nome_candidato = f"{nome_base} ({counter})"
            counter += 1

        try:
            budget_def = get_budget_annuo_default(conn)
            conn.execute("""
            INSERT INTO dipendenti (
                nome, email, totale_annuo, mattina_inizio, mattina_fine,
                pomeriggio_inizio, pomeriggio_fine, attivo, creato_il, aggiornato_il
            ) VALUES (?, ?, ?, '08:00', '12:00', '14:00', '18:00', 1, ?, ?)
            """, (nome_candidato, email, budget_def, now, now))
            aggiunti += 1
        except Exception:
            pass

    if aggiunti > 0:
        conn.commit()
    return aggiunti


# ------------------------------------------------------------------ Gestione Dipendenti
def get_dipendenti(conn: sqlite3.Connection, solo_attivi: bool = True) -> pd.DataFrame:
    """Restituisce il DataFrame di tutti i dipendenti registrati."""
    sql = "SELECT * FROM dipendenti"
    if solo_attivi:
        sql += " WHERE attivo = 1"
    sql += " ORDER BY nome ASC"
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame(columns=[
            "id", "nome", "email", "totale_annuo", "mattina_inizio",
            "mattina_fine", "pomeriggio_inizio", "pomeriggio_fine", "attivo"
        ])
    return df


def add_dipendente(
    conn: sqlite3.Connection,
    nome: str,
    email: str = "",
    totale_annuo: float | None = None,
    mattina_inizio: str = "08:00",
    mattina_fine: str = "12:00",
    pomeriggio_inizio: str = "14:00",
    pomeriggio_fine: str = "18:00"
) -> tuple[bool, str]:
    """Aggiunge un nuovo dipendente nel database."""
    nome = (nome or "").strip()
    if not nome:
        return False, "Il nome del dipendente è obbligatorio."

    if totale_annuo is None:
        totale_annuo = get_budget_annuo_default(conn)

    now = _now_iso()
    try:
        conn.execute("""
        INSERT INTO dipendenti (
            nome, email, totale_annuo, mattina_inizio, mattina_fine,
            pomeriggio_inizio, pomeriggio_fine, attivo, creato_il, aggiornato_il
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            nome, email.strip().lower(), float(totale_annuo),
            mattina_inizio, mattina_fine, pomeriggio_inizio, pomeriggio_fine,
            now, now
        ))
        conn.commit()
        return True, "Dipendente inserito con successo."
    except sqlite3.IntegrityError:
        return False, f"Un dipendente con nome '{nome}' esiste già."
    except Exception as e:
        return False, f"Errore durante l'inserimento: {e}"


def update_dipendente(
    conn: sqlite3.Connection,
    nome_originale: str,
    nuovo_nome: str,
    email: str,
    totale_annuo: float,
    orario_dict: dict[str, str]
) -> tuple[bool, str]:
    """Aggiorna i dati anagrafici, budget e orari di un dipendente."""
    now = _now_iso()
    nuovo_nome = (nuovo_nome or "").strip()
    if not nuovo_nome:
        return False, "Il nome non può essere vuoto."

    try:
        # Se il nome è cambiato, aggiorniamo a cascata anche lo storico ferie
        if nuovo_nome != nome_originale:
            conn.execute("UPDATE ferie_assenze SET nome = ? WHERE nome = ?", (nuovo_nome, nome_originale))

        conn.execute("""
        UPDATE dipendenti SET
            nome = ?,
            email = ?,
            totale_annuo = ?,
            mattina_inizio = ?,
            mattina_fine = ?,
            pomeriggio_inizio = ?,
            pomeriggio_fine = ?,
            aggiornato_il = ?
        WHERE nome = ?
        """, (
            nuovo_nome, email.strip().lower(), float(totale_annuo),
            orario_dict.get("mattina_inizio", "08:00"),
            orario_dict.get("mattina_fine", "12:00"),
            orario_dict.get("pomeriggio_inizio", "14:00"),
            orario_dict.get("pomeriggio_fine", "18:00"),
            now, nome_originale
        ))
        conn.commit()
        return True, "Dipendente aggiornato con successo."
    except sqlite3.IntegrityError:
        return False, f"Il nome '{nuovo_nome}' è già in uso da un altro dipendente."
    except Exception as e:
        return False, f"Errore durante l'aggiornamento: {e}"


def delete_dipendente(conn: sqlite3.Connection, nome: str) -> tuple[bool, str]:
    """Disattiva un dipendente (soft-delete per preservare lo storico)."""
    try:
        conn.execute("UPDATE dipendenti SET attivo = 0, aggiornato_il = ? WHERE nome = ?", (_now_iso(), nome))
        conn.commit()
        return True, f"Dipendente '{nome}' disattivato con successo."
    except Exception as e:
        return False, f"Errore durante l'eliminazione: {e}"


# ------------------------------------------------------------------ Orari e Calcoli
def _parse_ora(valore: Any, default_str: str) -> time:
    if valore is None or (isinstance(valore, float) and pd.isna(valore)):
        valore = default_str
    if isinstance(valore, time):
        return valore
    if isinstance(valore, datetime):
        return valore.time()
    s = str(valore).strip().replace(".", ":")
    if not s or s.lower() == "nan":
        s = default_str
    for fmt in ("%H:%M:%S", "%H:%M", "%H"):
        try:
            return datetime.strptime(s, fmt).time()
        except Exception:
            pass
    try:
        return datetime.strptime(default_str, "%H:%M").time()
    except Exception:
        return time(8, 0)


def get_orario_dipendente(row_dipendente: Any) -> dict[str, time]:
    """Estrae l'orario personale di un dipendente da una Series/dict."""
    getter = row_dipendente.get if hasattr(row_dipendente, "get") else (lambda k, d=None: getattr(row_dipendente, k, d))
    return {
        "mattina_inizio": _parse_ora(getter("mattina_inizio", None), ORARIO_DEFAULT["mattina_inizio"]),
        "mattina_fine": _parse_ora(getter("mattina_fine", None), ORARIO_DEFAULT["mattina_fine"]),
        "pomeriggio_inizio": _parse_ora(getter("pomeriggio_inizio", None), ORARIO_DEFAULT["pomeriggio_inizio"]),
        "pomeriggio_fine": _parse_ora(getter("pomeriggio_fine", None), ORARIO_DEFAULT["pomeriggio_fine"]),
    }


def ore_giornaliere_previste(orario: dict[str, time]) -> float:
    """Calcola le ore lavorative giornaliere previste per l'orario."""
    mattina = datetime.combine(_DATA_RIF_ORARIO, orario["mattina_fine"]) - datetime.combine(_DATA_RIF_ORARIO, orario["mattina_inizio"])
    pomeriggio = datetime.combine(_DATA_RIF_ORARIO, orario["pomeriggio_fine"]) - datetime.combine(_DATA_RIF_ORARIO, orario["pomeriggio_inizio"])
    return (mattina.total_seconds() + pomeriggio.total_seconds()) / 3600


def _ore_lavorate_mezza_giornata(assente: bool, ingresso_eff: time, uscita_eff: time) -> float:
    if assente:
        return 0.0
    dt_in = datetime.combine(_DATA_RIF_ORARIO, ingresso_eff)
    dt_out = datetime.combine(_DATA_RIF_ORARIO, uscita_eff)
    return max(0.0, (dt_out - dt_in).total_seconds() / 3600)


def calcola_giorni_da_permesso_orario(
    orario: dict[str, time],
    assente_mattina: bool, ingresso_mattina: time, uscita_mattina: time,
    assente_pomeriggio: bool, ingresso_pomeriggio: time, uscita_pomeriggio: time
) -> float:
    """Calcola la frazione di giorno scalata da un permesso orario."""
    ore_previste = ore_giornaliere_previste(orario)
    if ore_previste <= 0:
        return 0.0

    ore_mattina = _ore_lavorate_mezza_giornata(assente_mattina, ingresso_mattina, uscita_mattina)
    ore_pomeriggio = _ore_lavorate_mezza_giornata(assente_pomeriggio, ingresso_pomeriggio, uscita_pomeriggio)

    ore_mancanti = max(0.0, ore_previste - (ore_mattina + ore_pomeriggio))
    return round(ore_mancanti / ore_previste, 4)


def _descrivi_mezza_giornata(
    assente: bool,
    ingresso_eff: time,
    uscita_eff: time,
    ingresso_previsto: time,
    uscita_previsto: time
) -> str | None:
    """Descrive cosa è cambiato in una singola metà giornata rispetto all'orario previsto."""
    if assente:
        return "assente"
    parti: list[str] = []
    if ingresso_eff != ingresso_previsto:
        parti.append(f"entrata posticipata {ingresso_eff.strftime('%H:%M')}")
    if uscita_eff != uscita_previsto:
        parti.append(f"uscita anticipata {uscita_eff.strftime('%H:%M')}")
    return " e ".join(parti) if parti else None


def descrivi_permesso_orario(
    orario: dict[str, time],
    assente_mattina: bool, ingresso_mattina: time, uscita_mattina: time,
    assente_pomeriggio: bool, ingresso_pomeriggio: time, uscita_pomeriggio: time
) -> str:
    """Costruisce una breve descrizione testuale di un permesso orario (es.
    'Assente mattina', 'Uscita anticipata 16:00', 'Entrata posticipata 09:00 + Uscita anticipata 16:00'),
    da salvare nella colonna DETTAGLIO e mostrare nei tooltip dei calendari."""
    desc_mattina = _descrivi_mezza_giornata(
        assente_mattina, ingresso_mattina, uscita_mattina,
        orario["mattina_inizio"], orario["mattina_fine"]
    )
    desc_pomeriggio = _descrivi_mezza_giornata(
        assente_pomeriggio, ingresso_pomeriggio, uscita_pomeriggio,
        orario["pomeriggio_inizio"], orario["pomeriggio_fine"]
    )

    parti: list[str] = []
    if desc_mattina == "assente":
        parti.append("Assente mattina")
    elif desc_mattina:
        parti.append(desc_mattina.capitalize())

    if desc_pomeriggio == "assente":
        parti.append("Assente pomeriggio")
    elif desc_pomeriggio:
        parti.append(desc_pomeriggio.capitalize())

    return " + ".join(parti) if parti else "Permesso orario"


def calcola_giorni_lavorativi_esatti(inizio: date, fine: date) -> int:
    """Conta i giorni lavorativi (Lun-Ven esclusi festivi italiani) tra due date."""
    if fine < inizio:
        return 0
    it_holidays = holidays.Italy(years=list(range(inizio.year, fine.year + 1)))
    giorni = 0
    curr = inizio
    while curr <= fine:
        if curr.weekday() < 5 and curr not in it_holidays:
            giorni += 1
        curr += timedelta(days=1)
    return giorni


# ------------------------------------------------------------------ Ferie & Assenze CRUD
def get_ferie_storico(conn: sqlite3.Connection) -> pd.DataFrame:
    """Restituisce l'intero storico delle assenze registrate."""
    sql = "SELECT id, nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note, creato_il FROM ferie_assenze ORDER BY data_inizio DESC"
    df = pd.read_sql_query(sql, conn)
    if df.empty:
        return pd.DataFrame(columns=[
            "id", "nome", "data_inizio", "data_fine", "tipo", "giorni_lavorativi", "dettaglio", "note", "creato_il"
        ])
    return df


def check_overlaps(conn: sqlite3.Connection, inizio: date, fine: date, escludi_nome: str | None = None) -> list[str]:
    """Verifica se altri dipendenti hanno già assenze registrate nel periodo indicato."""
    df = get_ferie_storico(conn)
    if df.empty:
        return []

    overlaps = set()
    for _, row in df.iterrows():
        nome = str(row.get("nome", "")).strip()
        if escludi_nome and nome.lower() == escludi_nome.strip().lower():
            continue
        try:
            inizio_es = pd.to_datetime(row["data_inizio"]).date()
            fine_es = pd.to_datetime(row["data_fine"]).date()
            if inizio <= fine_es and inizio_es <= fine:
                overlaps.add(nome)
        except Exception:
            continue
    return sorted(list(overlaps))


def add_ferie(
    conn: sqlite3.Connection,
    nome: str,
    data_inizio: date,
    data_fine: date,
    tipo: str = "Ferie",
    note: str = "",
    dettaglio: str = ""
) -> tuple[bool, str]:
    """Inserisce un periodo di ferie / assenza a giorno intero."""
    nome = (nome or "").strip()
    if not nome:
        return False, "Il nome del dipendente è obbligatorio."
    if data_fine < data_inizio:
        return False, "La data di fine non può precedere la data di inizio."

    # Verifica sovrapposizione per lo stesso dipendente
    df = get_ferie_storico(conn)
    if not df.empty:
        dip_df = df[df["nome"].str.lower() == nome.lower()]
        for _, row in dip_df.iterrows():
            try:
                inizio_es = pd.to_datetime(row["data_inizio"]).date()
                fine_es = pd.to_datetime(row["data_fine"]).date()
                if data_inizio <= fine_es and inizio_es <= data_fine:
                    return False, f"{nome} ha già un'assenza registrata dal {inizio_es.strftime('%d/%m/%Y')} al {fine_es.strftime('%d/%m/%Y')}."
            except Exception:
                continue

    giorni = calcola_giorni_lavorativi_esatti(data_inizio, data_fine)
    dett = dettaglio if dettaglio else ("Rettifica" if tipo == "Rettifica" else "")
    now = _now_iso()

    try:
        conn.execute("""
        INSERT INTO ferie_assenze (
            nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note, creato_il
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            nome, data_inizio.isoformat(), data_fine.isoformat(),
            tipo, float(giorni), dett, note, now
        ))
        conn.commit()
        return True, "Assenza inserita con successo."
    except Exception as e:
        return False, f"Errore durante l'inserimento: {e}"


def add_permesso_orario(
    conn: sqlite3.Connection,
    nome: str,
    data_giorno: date,
    orario_dipendente: dict[str, time],
    assente_mattina: bool, ingresso_mattina: time, uscita_mattina: time,
    assente_pomeriggio: bool, ingresso_pomeriggio: time, uscita_pomeriggio: time,
    note: str = ""
) -> tuple[bool, str]:
    """Inserisce un permesso orario (frazione di giorno calcolata su ore effettive)."""
    frazione = calcola_giorni_da_permesso_orario(
        orario_dipendente, assente_mattina, ingresso_mattina, uscita_mattina,
        assente_pomeriggio, ingresso_pomeriggio, uscita_pomeriggio
    )
    dettaglio = descrivi_permesso_orario(
        orario_dipendente, assente_mattina, ingresso_mattina, uscita_mattina,
        assente_pomeriggio, ingresso_pomeriggio, uscita_pomeriggio
    )

    ha_variazione = (
        assente_mattina or assente_pomeriggio or
        ingresso_mattina != orario_dipendente["mattina_inizio"] or
        uscita_mattina != orario_dipendente["mattina_fine"] or
        ingresso_pomeriggio != orario_dipendente["pomeriggio_inizio"] or
        uscita_pomeriggio != orario_dipendente["pomeriggio_fine"]
    )
    if not ha_variazione:
        return False, "Nessuna variazione rispetto all'orario lavorativo previsto: nulla da registrare."

    now = _now_iso()
    try:
        conn.execute("""
        INSERT INTO ferie_assenze (
            nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note, creato_il
        ) VALUES (?, ?, ?, 'Permesso Orario', ?, ?, ?, ?)
        """, (
            nome, data_giorno.isoformat(), data_giorno.isoformat(),
            float(round(frazione, 4)), dettaglio, note, now
        ))
        conn.commit()
        return True, "Permesso orario registrato con successo."
    except Exception as e:
        return False, f"Errore durante il salvataggio: {e}"


def delete_ferie_riga(conn: sqlite3.Connection, riga_id: int) -> bool:
    """Elimina una riga di assenza tramite il suo ID primario."""
    try:
        conn.execute("DELETE FROM ferie_assenze WHERE id = ?", (int(riga_id),))
        conn.commit()
        return True
    except Exception:
        return False


def sync_ferie_changes(conn: sqlite3.Connection, nome_dipendente: str, edited_df: pd.DataFrame) -> tuple[bool, str]:
    """Sincronizza le modifiche dell'editor storico per un singolo dipendente."""
    try:
        # Rimuove le righe attuali del dipendente e le riscrive con quelle modificate
        conn.execute("DELETE FROM ferie_assenze WHERE nome = ?", (nome_dipendente,))
        now = _now_iso()

        if not edited_df.empty:
            for _, r in edited_df.iterrows():
                tipo = str(r.get("TIPO", "Ferie") or "Ferie")
                inizio_raw = r["DATA INIZIO"]
                fine_raw = r["DATA FINE"]
                inizio = pd.to_datetime(inizio_raw).date()
                fine = pd.to_datetime(fine_raw).date()
                dettaglio = str(r.get("DETTAGLIO", "") or "")
                note = str(r.get("NOTE", "") or "")

                # Mantieni giorni frazionari per permessi orari, altrimenti ricalcola
                giorni_val = pd.to_numeric(r.get("GIORNI LAVORATIVI"), errors="coerce")
                if tipo == "Permesso Orario" and pd.notna(giorni_val):
                    giorni = float(giorni_val)
                elif pd.notna(giorni_val) and giorni_val != int(giorni_val):
                    giorni = float(giorni_val)
                else:
                    giorni = float(calcola_giorni_lavorativi_esatti(inizio, fine))

                conn.execute("""
                INSERT INTO ferie_assenze (
                    nome, data_inizio, data_fine, tipo, giorni_lavorativi, dettaglio, note, creato_il
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    nome_dipendente, inizio.isoformat(), fine.isoformat(),
                    tipo, giorni, dettaglio, note, now
                ))

        conn.commit()
        return True, "Modifiche storiche salvate con successo."
    except Exception as e:
        conn.rollback()
        return False, f"Errore durante il salvataggio: {e}"


# ------------------------------------------------------------------ Saldi e Riporti
def calcola_riepilogo_ferie_annuale(df_storico: pd.DataFrame, nome: str, totale_annuo: float) -> dict[int, dict[str, float]]:
    """Calcola usati, disponibili e residuo anno per anno, con riporto del residuo precedente."""
    oggi_anno = datetime.now().year
    totale_annuo = float(totale_annuo) if totale_annuo not in (None, "") else DEFAULT_BUDGET_ANNUO

    date_valide: list[tuple[int, float]] = []
    if not df_storico.empty and "nome" in df_storico.columns:
        dip_ferie = df_storico[
            (df_storico["nome"].str.lower() == nome.lower()) &
            (df_storico["tipo"].isin(["Ferie", "Permesso Orario", "Rettifica"]))
        ]
        for _, riga in dip_ferie.iterrows():
            try:
                inizio_f = pd.to_datetime(riga["data_inizio"]).date()
            except Exception:
                continue
            giorni_val = pd.to_numeric(riga.get("giorni_lavorativi", 0), errors="coerce")
            date_valide.append((inizio_f.year, float(giorni_val) if pd.notna(giorni_val) else 0.0))

    anni = {a for a, _ in date_valide}
    anni.add(oggi_anno)
    anno_min, anno_max = min(anni), max(anni)

    riepilogo: dict[int, dict[str, float]] = {}
    residuo_precedente = 0.0
    for anno in range(anno_min, anno_max + 1):
        usati_anno = sum(g for a, g in date_valide if a == anno)
        disponibili_anno = totale_annuo + residuo_precedente
        residuo_anno = disponibili_anno - usati_anno
        riepilogo[anno] = {
            "usati": round(usati_anno, 2),
            "disponibili": round(disponibili_anno, 2),
            "residuo": round(residuo_anno, 2),
        }
        residuo_precedente = residuo_anno

    return riepilogo


def formatta_data_lunga(d: date) -> str:
    """Formatta una data in italiano: '10 Agosto 2026'."""
    return f"{d.day} {MESI_IT_LUNGO[d.month - 1]} {d.year}"


def formatta_giorni_ore(valore_giorni: float, ore_per_giorno: float = 8.0) -> str:
    """Formatta i giorni decimali come 'Ng Hh' (es. 4g 2h o -1g 4h)."""
    segno = "-" if valore_giorni < 0 else ""
    valore_assoluto = abs(valore_giorni)
    giorni_interi = int(valore_assoluto)
    resto = valore_assoluto - giorni_interi
    ore_residue = round(resto * ore_per_giorno)
    if ore_residue >= ore_per_giorno:
        giorni_interi += 1
        ore_residue = 0
    if ore_residue == 0:
        return f"{segno}{giorni_interi}g"
    return f"{segno}{giorni_interi}g {ore_residue}h"


# ------------------------------------------------------------------ Visualizzazioni Calendario HTML
def _colore_per_nome(nome: str) -> str:
    h = int(hashlib.md5(nome.encode("utf-8")).hexdigest(), 16)
    return _PALETTE_CALENDARIO[h % len(_PALETTE_CALENDARIO)]


def _assenze_nel_periodo(df_storico: pd.DataFrame, giorni: list[date]) -> dict[date, list[dict]]:
    assenze: dict[date, list[dict]] = {g: [] for g in giorni}
    if not df_storico.empty:
        for _, riga in df_storico.iterrows():
            try:
                inizio_f = pd.to_datetime(riga["data_inizio"]).date()
                fine_f = pd.to_datetime(riga["data_fine"]).date()
            except Exception:
                continue
            tipo = riga.get("tipo", "") or ""
            giorni_val = pd.to_numeric(riga.get("giorni_lavorativi"), errors="coerce")
            dettaglio = str(riga.get("dettaglio", "") or "").strip()
            for g in giorni:
                if inizio_f <= g <= fine_f:
                    assenze[g].append({
                        "nome": riga["nome"],
                        "tipo": tipo,
                        "giorni": giorni_val,
                        "dettaglio": dettaglio,
                        "inizio": inizio_f,
                        "fine": fine_f,
                    })
    return assenze


def _chip_html(assenza: dict, opacity: str = "1", ore_previste_dipendente: float = 8.0) -> str:
    nome = assenza["nome"]
    tipo = assenza.get("tipo") or ""
    giorni_val = assenza.get("giorni")
    dettaglio = assenza.get("dettaglio") or ""
    colore = _colore_per_nome(nome)
    primo_nome = str(nome).split()[0] if nome else "?"

    is_parziale = (tipo == "Permesso Orario")

    if tipo and tipo not in ["Ferie", "Permesso Orario"]:
        descrizione = tipo
        icona = ""
    elif is_parziale and dettaglio:
        descrizione = dettaglio
        icona = "🕐 "
    elif is_parziale:
        try:
            ore_stimate = round(float(giorni_val) * ore_previste_dipendente * 2) / 2
            descrizione = f"Permesso orario (~{ore_stimate:g}h)"
        except Exception:
            descrizione = "Permesso orario"
        icona = "🕐 "
    else:
        descrizione = "Ferie"
        icona = ""

    if is_parziale:
        tooltip = f"🕐 {nome} — {descrizione}"
    else:
        tooltip = f"{nome} — {descrizione}"

    inizio_a, fine_a = assenza.get("inizio"), assenza.get("fine")
    if inizio_a and fine_a and inizio_a != fine_a:
        if (dettaglio or "").lower() == "rettifica":
            tooltip += " — Rettifica"
        else:
            tooltip += f" (dal {inizio_a.strftime('%d/%m')} al {fine_a.strftime('%d/%m')})"

    return (
        f'<div title="{tooltip}" style="background:{colore}18; color:{colore}; '
        f'border:1px solid {colore}44; border-radius:4px; padding:2px 5px; '
        f'font-size:11px; font-weight:600; margin-top:3px; white-space:nowrap; '
        f'overflow:hidden; text-overflow:ellipsis; opacity:{opacity};">{icona}{primo_nome}</div>'
    )


def build_calendario_mensile_html(df_storico: pd.DataFrame, anno: int, mese: int) -> str:
    """Genera la tabella visuale completa del mese in stile pulito C-Level."""
    oggi = datetime.now().date()
    primo_giorno = date(anno, mese, 1)
    ultimo_giorno_num = _calendar_mod.monthrange(anno, mese)[1]
    ultimo_giorno = date(anno, mese, ultimo_giorno_num)

    inizio_griglia = primo_giorno - timedelta(days=primo_giorno.weekday())
    fine_griglia = ultimo_giorno + timedelta(days=(6 - ultimo_giorno.weekday()))

    giorni_totali: list[date] = []
    g = inizio_griglia
    while g <= fine_griglia:
        giorni_totali.append(g)
        g += timedelta(days=1)

    assenze_per_giorno = _assenze_nel_periodo(df_storico, giorni_totali)
    anni_griglia = {d.year for d in giorni_totali}
    festivi_it = holidays.Italy(years=list(anni_griglia))

    html = ['<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin-top:10px;">']
    html.append('<div style="overflow-x:auto;">')
    html.append('<div style="display:grid; grid-template-columns:repeat(7, 1fr); gap:6px; min-width:650px;">')

    # Intestazioni giorni della settimana
    for giorno_sett in _GIORNI_IT:
        html.append(
            f'<div style="text-align:center; font-size:11px; font-weight:700; color:#64748B; '
            f'text-transform:uppercase; padding:4px 0;">{giorno_sett}</div>'
        )

    for curr_g in giorni_totali:
        is_oggi = (curr_g == oggi)
        e_weekend = curr_g.weekday() >= 5
        e_festivo = curr_g in festivi_it
        fuori_mese = (curr_g.month != mese)

        if fuori_mese:
            bg = "#F8FAFC"
            border = "1px solid #E2E8F0"
            color_num = "#94A3B8"
            opacity_chip = "0.45"
            assenze_g = [] if (e_weekend or e_festivo) else assenze_per_giorno[curr_g]
        elif is_oggi:
            bg = "#F0FDFA"
            border = "2px solid #0D9488"
            color_num = "#0D9488"
            opacity_chip = "1.0"
            assenze_g = [] if (e_weekend or e_festivo) else assenze_per_giorno[curr_g]
        elif e_festivo:
            bg = "#FEF3C7"
            border = "1px solid #FDE68A"
            color_num = "#B45309"
            opacity_chip = "1.0"
            assenze_g = []
        elif e_weekend:
            bg = "#F1F5F9"
            border = "1px solid #E2E8F0"
            color_num = "#64748B"
            opacity_chip = "1.0"
            assenze_g = []
        else:
            bg = "#FFFFFF"
            border = "1px solid #CBD5E1"
            color_num = "#0F172A"
            opacity_chip = "1.0"
            assenze_g = assenze_per_giorno[curr_g]

        chips = "".join(_chip_html(a, opacity_chip) for a in assenze_g if (a.get("dettaglio") or "").lower() != "rettifica")

        html.append(
            f'<div style="background:{bg}; border:{border}; border-radius:6px; padding:6px; min-height:80px;">'
            f'<div style="font-size:13px; font-weight:700; color:{color_num};">{curr_g.day}</div>'
            f'{chips}'
            f'</div>'
        )

    html.append('</div></div></div>')
    return "".join(html)


def build_calendario_settimanale_html(df_storico: pd.DataFrame) -> str:
    """Genera la visualizzazione a 2 settimane lavorative (Lun-Ven: corrente e successiva)."""
    oggi = datetime.now().date()
    inizio_settimana = oggi - timedelta(days=oggi.weekday())
    giorni_totali = [inizio_settimana + timedelta(days=i) for i in range(14)]
    assenze_per_giorno = _assenze_nel_periodo(df_storico, giorni_totali)

    anni_griglia = {g.year for g in giorni_totali}
    festivi_it = holidays.Italy(years=list(anni_griglia))

    html = ['<div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif;">']

    for sett_idx in range(2):
        sett_giorni_full = giorni_totali[sett_idx * 7:(sett_idx + 1) * 7]
        # Mostra solo Lunedì-Venerdì
        sett_giorni = [g for g in sett_giorni_full if g.weekday() < 5]
        label = "Settimana Corrente" if sett_idx == 0 else "Prossima Settimana"
        m_top = "0" if sett_idx == 0 else "18px"

        html.append(
            f'<div style="font-size:11px; font-weight:700; color:#475569; text-transform:uppercase; '
            f'letter-spacing:0.5px; margin:{m_top} 0 8px 2px;">{label}</div>'
        )
        html.append('<div style="overflow-x:auto;">')
        html.append('<div style="display:grid; grid-template-columns:repeat(5, 1fr); gap:8px; min-width:480px;">')

        for g in sett_giorni:
            is_oggi = (g == oggi)
            e_festivo = g in festivi_it
            assenze_g = [] if e_festivo else assenze_per_giorno[g]

            if is_oggi:
                bg = "#F0FDFA"
                border = "2px solid #0D9488"
                num_col = "#0D9488"
            elif e_festivo:
                bg = "#FEF3C7"
                border = "1px solid #FDE68A"
                num_col = "#B45309"
            else:
                bg = "#FFFFFF"
                border = "1px solid #CBD5E1"
                num_col = "#0F172A"

            chips = "".join(_chip_html(a) for a in assenze_g if (a.get("dettaglio") or "").lower() != "rettifica")
            giorno_label = _GIORNI_IT[g.weekday()]
            mese_label = f" {_MESI_IT[g.month - 1]}" if (g.day == 1 or g == giorni_totali[0]) else ""

            html.append(
                f'<div style="background:{bg}; border:{border}; border-radius:6px; padding:8px; min-height:85px;">'
                f'<div style="font-size:10px; color:#64748B; font-weight:700; text-transform:uppercase;">{giorno_label}</div>'
                f'<div style="font-size:15px; font-weight:700; color:{num_col};">{g.day}{mese_label}</div>'
                f'{chips}'
                f'</div>'
            )

        html.append('</div></div>')

    html.append('</div>')
    return "".join(html)
