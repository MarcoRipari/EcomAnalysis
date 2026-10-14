"""
Gestione Ruoli e Controllo Accessi (RBAC) per EcomAnalysis.

Modello di autorizzazione:
- Ogni utente ha un ruolo assegnato per email (tabella `utenti_ruoli`).
- Ogni ruolo dispone di un insieme di permessi corrispondenti alle pagine abilitate (tabella `permessi_ruolo`).
- Ruoli predefiniti di sistema:
  * Admin: Accesso integrale a tutti i moduli, configurazioni e gestione permessi.
  * Finance: Accesso alla Homepage, a tutti i report di Analisi Dati, Export Dati e profilo personale.
  * Logistica: Accesso alla Homepage, Gestione Catalogo, Gestione Foto e profilo personale.
- Ulteriori ruoli personalizzati possono essere creati ed eliminati liberamente dall'amministratore.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

# Metadata completo di tutte le pagine censite nel sistema
PAGINE_METADATA: list[dict[str, str]] = [
    # Homepage
    {"id": "00_Home", "titolo": "Homepage", "gruppo": "Homepage", "file": "pages/00_Home.py"},

    # Analisi Dati
    {"id": "01_Dashboard", "titolo": "Dashboard", "gruppo": "Analisi Dati", "file": "pages/01_Dashboard.py"},
    {"id": "02_Y2Y_Generale", "titolo": "Y2Y Generale", "gruppo": "Analisi Dati", "file": "pages/02_Y2Y_Generale.py"},
    {"id": "04_Canali_Marketplace", "titolo": "Canali & Marketplace", "gruppo": "Analisi Dati", "file": "pages/04_Canali_Marketplace.py"},
    {"id": "05_Nazioni", "titolo": "Nazioni & Geografia", "gruppo": "Analisi Dati", "file": "pages/05_Nazioni.py"},
    {"id": "03_Articoli_e_Collezioni", "titolo": "Articoli & Collezioni", "gruppo": "Analisi Dati", "file": "pages/03_Articoli_e_Collezioni.py"},
    {"id": "06_Analisi_Resi", "titolo": "Analisi Resi", "gruppo": "Analisi Dati", "file": "pages/06_Analisi_Resi.py"},
    {"id": "07_Trova_SKU", "titolo": "Trova SKU", "gruppo": "Analisi Dati", "file": "pages/07_Trova_SKU.py"},
    {"id": "08_Taglie", "titolo": "Taglie per Brand", "gruppo": "Analisi Dati", "file": "pages/08_Taglie.py"},
    {"id": "09_Sell_Through", "titolo": "Sell-Through", "gruppo": "Analisi Dati", "file": "pages/09_Sell_Through.py"},

    # Gestione Catalogo
    {"id": "20_Catalogo_Panoramica", "titolo": "Panoramica Catalogo", "gruppo": "Gestione Catalogo", "file": "pages/20_Catalogo_Panoramica.py"},
    {"id": "21_Catalogo_Articoli", "titolo": "Articoli & Listini", "gruppo": "Gestione Catalogo", "file": "pages/21_Catalogo_Articoli.py"},

    # Gestione Foto
    {"id": "22_Foto_Archivio", "titolo": "Archivio Fotografico", "gruppo": "Gestione Foto", "file": "pages/22_Foto_Archivio.py"},
    {"id": "23_Foto_Caricamento", "titolo": "Carica & Associa", "gruppo": "Gestione Foto", "file": "pages/23_Foto_Caricamento.py"},

    # Ferie
    {"id": "24_Ferie_Calendario", "titolo": "Calendario", "gruppo": "Ferie", "file": "pages/24_Ferie_Calendario.py"},
    {"id": "25_Ferie_Registra", "titolo": "Registra Ferie & Permessi", "gruppo": "Ferie", "file": "pages/25_Ferie_Registra.py"},
    {"id": "26_Ferie_Riepilogo", "titolo": "Riepilogo", "gruppo": "Ferie", "file": "pages/26_Ferie_Riepilogo.py"},
    {"id": "27_Ferie_Configurazioni", "titolo": "Configurazioni", "gruppo": "Ferie", "file": "pages/27_Ferie_Configurazioni.py"},

    # Export & Sistema
    {"id": "00_Carica_Dati", "titolo": "Carica Dati", "gruppo": "Export & Sistema", "file": "pages/00_Carica_Dati.py"},
    {"id": "15_Anagrafica", "titolo": "Anagrafica Articoli", "gruppo": "Export & Sistema", "file": "pages/15_Anagrafica.py"},
    {"id": "10_Export_Dati", "titolo": "Export Dati", "gruppo": "Export & Sistema", "file": "pages/10_Export_Dati.py"},
    {"id": "14_Configurazioni", "titolo": "Configurazioni", "gruppo": "Export & Sistema", "file": "pages/14_Configurazioni.py"},
    {"id": "13_Correzioni_DB", "titolo": "Correzioni DB", "gruppo": "Export & Sistema", "file": "pages/13_Correzioni_DB.py"},
    {"id": "11_Log_Riconciliazione", "titolo": "Log Riconciliazione", "gruppo": "Export & Sistema", "file": "pages/11_Log_Riconciliazione.py"},
    {"id": "12_Account", "titolo": "Account e Sicurezza", "gruppo": "Export & Sistema", "file": "pages/12_Account.py"},
    {"id": "16_Gestione_Ruoli", "titolo": "Gestione Ruoli & Permessi", "gruppo": "Export & Sistema", "file": "pages/16_Gestione_Ruoli.py"},
    {"id": "17_Nuovo_Utente", "titolo": "Crea Nuovo Utente", "gruppo": "Export & Sistema", "file": "pages/17_Nuovo_Utente.py"},
    {"id": "18_Stato_Connessioni", "titolo": "Stato Connessioni", "gruppo": "Export & Sistema", "file": "pages/18_Stato_Connessioni.py"},

    # Test & Strumenti (solo Admin)
    {"id": "99_Test_Chatbot", "titolo": "TEST Chatbot", "gruppo": "Test (Admin)", "file": "pages/99_Test_Chatbot.py"},
]

ALL_PAGE_IDS: list[str] = [p["id"] for p in PAGINE_METADATA]

DEFAULT_ROLES: list[dict[str, Any]] = [
    {
        "nome": "Admin",
        "descrizione": "Amministratore di sistema: accesso completo a tutti i moduli e alla configurazione ruoli.",
        "is_system": 1,
        "pagine": ALL_PAGE_IDS,
    },
    {
        "nome": "Finance",
        "descrizione": "Profilo direzionale economico: accesso a Homepage, report Analisi Dati, Export Dati e profilo account.",
        "is_system": 0,
        "pagine": [
            "00_Home",
            "01_Dashboard",
            "02_Y2Y_Generale",
            "04_Canali_Marketplace",
            "05_Nazioni",
            "03_Articoli_e_Collezioni",
            "06_Analisi_Resi",
            "07_Trova_SKU",
            "08_Taglie",
            "09_Sell_Through",
            "10_Export_Dati",
            "24_Ferie_Calendario",
            "25_Ferie_Registra",
            "26_Ferie_Riepilogo",
            "12_Account",
        ],
    },
    {
        "nome": "Logistica",
        "descrizione": "Profilo operativo merci e catalogo: accesso a Homepage, Gestione Catalogo, Gestione Foto e profilo account.",
        "is_system": 0,
        "pagine": [
            "00_Home",
            "20_Catalogo_Panoramica",
            "21_Catalogo_Articoli",
            "22_Foto_Archivio",
            "23_Foto_Caricamento",
            "24_Ferie_Calendario",
            "25_Ferie_Registra",
            "26_Ferie_Riepilogo",
            "12_Account",
        ],
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_roles(conn: sqlite3.Connection) -> None:
    """Inizializza tabelle e ruoli predefiniti se non ancora presenti nel database."""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS ruoli (
        nome TEXT PRIMARY KEY,
        descrizione TEXT NOT NULL DEFAULT '',
        is_system INTEGER NOT NULL DEFAULT 0,
        creato_il TEXT NOT NULL
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS permessi_ruolo (
        ruolo TEXT NOT NULL,
        pagina_id TEXT NOT NULL,
        attivo INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (ruolo, pagina_id)
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS utenti_ruoli (
        email TEXT PRIMARY KEY,
        ruolo TEXT NOT NULL,
        assegnato_il TEXT NOT NULL
    );
    """)

    count = conn.execute("SELECT COUNT(*) FROM ruoli").fetchone()[0]
    now = _now_iso()

    if count == 0:
        for r in DEFAULT_ROLES:
            conn.execute(
                "INSERT INTO ruoli (nome, descrizione, is_system, creato_il) VALUES (?, ?, ?, ?)",
                (r["nome"], r["descrizione"], r["is_system"], now),
            )
            for p_id in r["pagine"]:
                conn.execute(
                    "INSERT INTO permessi_ruolo (ruolo, pagina_id, attivo) VALUES (?, ?, 1)",
                    (r["nome"], p_id),
                )
        conn.commit()
    else:
        # Garanzia: il ruolo Admin ha SEMPRE tutte le pagine definite
        for p_id in ALL_PAGE_IDS:
            conn.execute(
                "INSERT OR IGNORE INTO permessi_ruolo (ruolo, pagina_id, attivo) VALUES ('Admin', ?, 1)",
                (p_id,),
            )
        for r_name in ["Finance", "Logistica"]:
            for f_page in ["24_Ferie_Calendario", "25_Ferie_Registra", "26_Ferie_Riepilogo"]:
                conn.execute(
                    "INSERT OR IGNORE INTO permessi_ruolo (ruolo, pagina_id, attivo) VALUES (?, ?, 1)",
                    (r_name, f_page),
                )
        conn.commit()


def get_all_roles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Ritorna l'elenco di tutti i ruoli configurati."""
    rows = conn.execute(
        "SELECT nome, descrizione, is_system, creato_il FROM ruoli ORDER BY is_system DESC, nome ASC"
    ).fetchall()
    return [
        {"nome": r[0], "descrizione": r[1], "is_system": bool(r[2]), "creato_il": r[3]}
        for r in rows
    ]


def create_role(
    conn: sqlite3.Connection, nome: str, descrizione: str, permessi: list[str] | None = None
) -> tuple[bool, str]:
    """Crea un nuovo ruolo con la descrizione e i permessi indicati."""
    nome_pulito = nome.strip()
    if not nome_pulito:
        return False, "Il nome del ruolo non può essere vuoto."
    if len(nome_pulito) < 2 or len(nome_pulito) > 30:
        return False, "Il nome del ruolo deve contenere tra 2 e 30 caratteri."

    esiste = conn.execute("SELECT 1 FROM ruoli WHERE LOWER(nome) = LOWER(?)", (nome_pulito,)).fetchone()
    if esiste:
        return False, f"Il ruolo '{nome_pulito}' esiste già."

    now = _now_iso()
    conn.execute(
        "INSERT INTO ruoli (nome, descrizione, is_system, creato_il) VALUES (?, ?, 0, ?)",
        (nome_pulito, descrizione.strip(), now),
    )

    pagine_da_abilitare = permessi if permessi is not None else ["00_Home", "12_Account"]
    for p_id in pagine_da_abilitare:
        if p_id in ALL_PAGE_IDS:
            conn.execute(
                "INSERT INTO permessi_ruolo (ruolo, pagina_id, attivo) VALUES (?, ?, 1)",
                (nome_pulito, p_id),
            )
    conn.commit()
    return True, f"Ruolo '{nome_pulito}' creato con successo."


def delete_role(conn: sqlite3.Connection, nome: str) -> tuple[bool, str]:
    """Elimina un ruolo personalizzato (i ruoli di sistema come Admin non possono essere eliminati)."""
    row = conn.execute("SELECT is_system FROM ruoli WHERE nome = ?", (nome,)).fetchone()
    if not row:
        return False, f"Ruolo '{nome}' non trovato."
    if row[0]:
        return False, f"Il ruolo '{nome}' è un ruolo di sistema protetto e non può essere eliminato."

    # Riassegna eventuali utenti di questo ruolo al ruolo predefinito 'Finance'
    conn.execute("UPDATE utenti_ruoli SET ruolo = 'Finance' WHERE ruolo = ?", (nome,))
    conn.execute("DELETE FROM permessi_ruolo WHERE ruolo = ?", (nome,))
    conn.execute("DELETE FROM ruoli WHERE nome = ?", (nome,))
    conn.commit()
    return True, f"Ruolo '{nome}' eliminato con successo. Gli utenti associati sono stati riassegnati a Finance."


def get_role_permissions(conn: sqlite3.Connection, role_name: str) -> set[str]:
    """Ritorna l'insieme degli ID pagina abilitati per il ruolo specificato."""
    if role_name == "Admin":
        return set(ALL_PAGE_IDS)

    rows = conn.execute(
        "SELECT pagina_id FROM permessi_ruolo WHERE ruolo = ? AND attivo = 1", (role_name,)
    ).fetchall()
    return {r[0] for r in rows}


def set_role_permissions(
    conn: sqlite3.Connection, role_name: str, allowed_page_ids: list[str]
) -> tuple[bool, str]:
    """Aggiorna i permessi per un ruolo (Admin conserva sempre accesso totale)."""
    if role_name == "Admin":
        return True, "Il ruolo Admin dispone permanentemente di accesso a tutte le sezioni."

    conn.execute("DELETE FROM permessi_ruolo WHERE ruolo = ?", (role_name,))
    for p_id in allowed_page_ids:
        if p_id in ALL_PAGE_IDS:
            conn.execute(
                "INSERT INTO permessi_ruolo (ruolo, pagina_id, attivo) VALUES (?, ?, 1)",
                (role_name, p_id),
            )
    conn.commit()
    return True, f"Permessi aggiornati per il ruolo '{role_name}'."


def get_user_role(conn: sqlite3.Connection, email: str | None) -> str:
    """Ritorna il ruolo dell'utente per email.
    Se il database non ha ancora utenti censiti, il primo utente diventa Admin automaticamente."""
    if not email:
        return "Admin"

    email_clean = email.strip().lower()
    row = conn.execute("SELECT ruolo FROM utenti_ruoli WHERE LOWER(email) = ?", (email_clean,)).fetchone()
    if row:
        # Verifica che il ruolo esista ancora
        r_esiste = conn.execute("SELECT 1 FROM ruoli WHERE nome = ?", (row[0],)).fetchone()
        return row[0] if r_esiste else "Admin"

    # Nessuna assegnazione trovata: verifica se è il primo utente assoluto
    tot_utenti = conn.execute("SELECT COUNT(*) FROM utenti_ruoli").fetchone()[0]
    if tot_utenti == 0:
        set_user_role(conn, email_clean, "Admin")
        return "Admin"

    # Default per nuovi utenti non ancora assegnati: Finance (consultazione)
    return "Finance"


def set_user_role(conn: sqlite3.Connection, email: str, role_name: str) -> tuple[bool, str]:
    """Assegna un ruolo a un utente per email."""
    email_clean = email.strip().lower()
    if not email_clean or "@" not in email_clean:
        return False, "Indirizzo email non valido."

    r_esiste = conn.execute("SELECT 1 FROM ruoli WHERE nome = ?", (role_name,)).fetchone()
    if not r_esiste:
        return False, f"Il ruolo '{role_name}' non esiste."

    now = _now_iso()
    conn.execute("""
    INSERT INTO utenti_ruoli (email, ruolo, assegnato_il)
    VALUES (?, ?, ?)
    ON CONFLICT(email) DO UPDATE SET ruolo = excluded.ruolo, assegnato_il = excluded.assegnato_il
    """, (email_clean, role_name, now))
    conn.commit()
    return True, f"Ruolo '{role_name}' assegnato all'utente '{email_clean}'."


def get_all_users(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """Ritorna tutti gli utenti con assegnazione ruolo."""
    rows = conn.execute(
        "SELECT email, ruolo, assegnato_il FROM utenti_ruoli ORDER BY email ASC"
    ).fetchall()
    return [{"email": r[0], "ruolo": r[1], "assegnato_il": r[2]} for r in rows]


def delete_user_role(conn: sqlite3.Connection, email: str) -> tuple[bool, str]:
    """Rimuove l'assegnazione ruolo di un utente (bloccato se è l'unico Admin rimasto)."""
    email_clean = email.strip().lower()
    row = conn.execute("SELECT ruolo FROM utenti_ruoli WHERE LOWER(email) = ?", (email_clean,)).fetchone()
    if not row:
        return False, f"Utente '{email_clean}' non trovato."

    if row[0] == "Admin":
        count_admins = conn.execute(
            "SELECT COUNT(*) FROM utenti_ruoli WHERE ruolo = 'Admin'"
        ).fetchone()[0]
        if count_admins <= 1:
            return False, "Impossibile rimuovere l'unico amministratore (Admin) registrato nel sistema."

    conn.execute("DELETE FROM utenti_ruoli WHERE LOWER(email) = ?", (email_clean,))
    conn.commit()
    return True, f"Assegnazione per '{email_clean}' rimossa con successo."


def get_groups_metadata() -> dict[str, list[dict[str, str]]]:
    """Raggruppa le pagine per macro-area (gruppo) per una resa grafica chiara nella matrice permessi."""
    gruppi: dict[str, list[dict[str, str]]] = {}
    for p in PAGINE_METADATA:
        g = p["gruppo"]
        if g not in gruppi:
            gruppi[g] = []
        gruppi[g].append(p)
    return gruppi
