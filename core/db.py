"""
Livello di persistenza: un DB SQLite che accumula tutte le righe caricate (DATASET e RESI),
con lo stato di riconciliazione (Spedito/Reso) "cristallizzato" riga per riga al momento del
caricamento — non più ricalcolato ogni volta in memoria.

Idea chiave: ogni riga ha un ID stabile = hash del contenuto (ordine, riga, sku, taglia, data
vendita, acquirente, importo, qta) + un contatore di occorrenza per gestire righe duplicate
legittime (stesso ordine/sku/taglia comprato più volte). Il ricarico dello stesso file è quindi
idempotente: le righe già presenti vengono ignorate, non duplicate.

Upload DATASET -> INSERT (stato iniziale: Spedito, o Reso se il file lo marca già così).
Upload RESI     -> per ogni riga, cerca la corrispondente con la cascata a due chiavi di
                    cascata (prima ordine+riga+sku+taglia, poi il composito
                    mkp+naz+acquirente+sku+taglia+importo), su TUTTE le righe (Spedito e Reso):
                    già Reso -> duplicato, no-op; Spedito -> UPDATE a Reso; nessuna riga ->
                    il reso viene aggiunto come ordine reale (con la sua data vendita e la
                    sua data reso; is_rimborso_extra=1 ricorda che l'ordine non era nel DB e
                    verrà assorbito se il DATASET arriva dopo). Includere anche le righe già Reso nella
                    ricerca è ciò che rende il ricarico RESI idempotente.

Query per range di date: "venduto nel periodo" = data_vendita nel range (un reso il cui
data_reso NON è nello stesso range conta come spedito puro per quel periodo); "reso extra nel
periodo" = data_reso nel range ma vendita fuori range = "resi fuori periodo". Fatturato = venduto - resi nel periodo - resi fuori periodo (core/metrics.py).
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import correzioni

DEFAULT_DB_PATH = "data/ecombi.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS righe (
    id TEXT PRIMARY KEY,
    key_ordine TEXT NOT NULL,
    key_composito TEXT NOT NULL,
    mkp TEXT, nazione TEXT, clz_originale TEXT, clz_mappata TEXT,
    sku_full TEXT, sku13 TEXT, sku7 TEXT, taglia TEXT, genere TEXT, acquirente TEXT,
    paia_spedite REAL, netto_spedito REAL, lordo_spedito REAL,
    data_vendita TEXT, data_reso TEXT,
    ordine_id TEXT, riga_ordine TEXT, tipo_spedizione TEXT, is_promo INTEGER,
    status TEXT NOT NULL DEFAULT 'Spedito',
    is_rimborso_extra INTEGER NOT NULL DEFAULT 0,
    matched_via TEXT,
    fonte_file TEXT, caricato_il TEXT
);
CREATE INDEX IF NOT EXISTS idx_key_ordine ON righe(key_ordine, status);
CREATE INDEX IF NOT EXISTS idx_key_composito ON righe(key_composito, status);
CREATE INDEX IF NOT EXISTS idx_data_vendita ON righe(data_vendita);
CREATE INDEX IF NOT EXISTS idx_data_reso ON righe(data_reso);
CREATE INDEX IF NOT EXISTS idx_sku13 ON righe(sku13);

CREATE TABLE IF NOT EXISTS log_match (
    ts TEXT, fonte_file TEXT, esito TEXT,
    ordine_id TEXT, ordine_id_resi TEXT, sku13 TEXT, key_comp TEXT, modalita TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_fonte ON log_match(fonte_file);

CREATE TABLE IF NOT EXISTS regole_correzione (
    id INTEGER PRIMARY KEY AUTOINCREMENT, creata_il TEXT, colonna TEXT, operatore TEXT, cerca TEXT,
    sostituisci TEXT, modo TEXT, ignora_maiuscole INTEGER, condizioni TEXT, data_da TEXT, data_a TEXT,
    attiva INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS log_correzioni (
    ts TEXT, colonna TEXT, operatore TEXT, cerca TEXT, sostituisci TEXT, modo TEXT, condizioni TEXT, righe INTEGER
);

CREATE TABLE IF NOT EXISTS upload_log (
    ts TEXT, fonte_file TEXT, tipo TEXT, righe_nel_file INTEGER,
    righe_nuove INTEGER, righe_gia_presenti INTEGER,
    convertiti INTEGER, duplicati INTEGER, standalone INTEGER
);

CREATE TABLE IF NOT EXISTS impostazioni (
    chiave TEXT PRIMARY KEY,
    valore TEXT NOT NULL,
    aggiornato_il TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anagrafica (
    sku13 TEXT PRIMARY KEY,
    sku7 TEXT NOT NULL,
    brand_cod TEXT,
    brand TEXT,
    linea_cod TEXT,
    linea TEXT,
    reparto_cod TEXT,
    tipo_cod TEXT,
    categoria TEXT,
    descrizione TEXT,
    fondo_cod TEXT,
    fondo_desc TEXT,
    colore_cod TEXT,
    colore_desc TEXT,
    taglia_base TEXT,
    valore TEXT,
    data_disponibilita TEXT,
    flag TEXT,
    stagione TEXT,
    semestre TEXT,
    genere TEXT,
    fonte_file TEXT,
    aggiornato_il TEXT
);
CREATE INDEX IF NOT EXISTS idx_anagrafica_sku7 ON anagrafica(sku7);
CREATE INDEX IF NOT EXISTS idx_anagrafica_brand ON anagrafica(brand);
CREATE INDEX IF NOT EXISTS idx_anagrafica_genere ON anagrafica(genere);
CREATE INDEX IF NOT EXISTS idx_sku7 ON righe(sku7);

CREATE TABLE IF NOT EXISTS regole_anagrafica (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    valore TEXT NOT NULL,
    attivo INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT '',
    creato_il TEXT NOT NULL,
    UNIQUE(tipo, valore)
);
CREATE INDEX IF NOT EXISTS idx_regole_anagrafica_tipo ON regole_anagrafica(tipo, attivo);
"""


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# --------------------------------------------------------------------------------------
# Chiavi / hash
# --------------------------------------------------------------------------------------

def _key_ordine_series(df: pd.DataFrame) -> pd.Series:
    return (df["ordineId"].astype(str) + "|" + df["rigaOrdine"].astype(str) + "|" +
            df["sku13"].astype(str) + "|" + df["taglia"].astype(str))


def _key_composito_series(df: pd.DataFrame) -> pd.Series:
    """Chiave composita SEMPRE di contenuto: mkp|nazione|acquirente|sku13|taglia|lordo(centesimi).

    Niente fallback "__SPURIOUS__<indice>": era posizionale (l'indice della riga nel proprio
    dataframe) e collideva tra file diversi — il reso in posizione j del RESI "matchava" la
    riga spedita in posizione j del DATASET anche se ordine/sku/acquirente non c'entravano
    nulla. Eliminato anche il guard sulla whitelist: il match composito vale per tutti i
    marketplace (per gli acquirenti anonimi è semplicemente più selettivo sul resto della
    chiave, e la regola resta: match trovato -> RESO no-op / SPEDITO converti; nessun match ->
    reso aggiunto senza ordine).
    """
    lordo_cents = (df["lordoSpedito"].astype(float) * 100).round().astype("int64").astype(str)
    return (df["mkp"].astype(str) + "|" + df["nazione"].astype(str) + "|" +
            df["acquirente"].astype(str) + "|" + df["sku13"].astype(str) + "|" +
            df["taglia"].astype(str) + "|" + lordo_cents)


def _content_hash_series(df: pd.DataFrame) -> pd.Series:
    raw = (df["ordineId"].astype(str) + "|" + df["rigaOrdine"].astype(str) + "|" + df["sku13"].astype(str) + "|" +
           df["taglia"].astype(str) + "|" + df["dataVendita"].astype(str) + "|" + df["acquirente"].astype(str) + "|" +
           (df["lordoSpedito"].astype(float) * 100).round().astype("int64").astype(str) + "|" +
           df["paiaSpedite"].astype(str))
    return raw.map(lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest()[:16])


def _chunked(seq, size=500):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _fmt_date(x) -> str | None:
    if x is None or (isinstance(x, float) and pd.isna(x)) or pd.isna(x):
        return None
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def _fmt_date_series(s: pd.Series) -> list:
    """Come _fmt_date ma vettoriale: su 100k+ righe evita una chiamata Python per elemento."""
    out = pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")
    return out.where(pd.to_datetime(s, errors="coerce").notna(), None).tolist()


def _build_records(df: pd.DataFrame, row_id, key_ordine, key_composito, status, is_rimborso_extra: int,
                    matched_via, fonte_file: str, now: str) -> list[tuple]:
    """Costruisce la lista di tuple per l'INSERT in modo vettoriale (zip di array), non con un
    ciclo `.iloc[i]` — su file da centinaia di migliaia di righe la differenza è enorme
    (l'accesso `.iloc[i]` riga per riga crea un oggetto Series ad ogni chiamata ed è
    tipicamente 100-1000 volte più lento dell'equivalente vettoriale)."""
    n = len(df)
    if isinstance(status, str):
        status = [status] * n
    matched_via_list = matched_via if isinstance(matched_via, list) else [matched_via] * n
    return list(zip(
        row_id, key_ordine, key_composito,
        df["mkp"].astype(str).to_numpy(), df["nazione"].astype(str).to_numpy(),
        df["clzOriginale"].astype(str).to_numpy(), df["clzMappata"].astype(str).to_numpy(),
        df["skuFull"].astype(str).to_numpy(), df["sku13"].astype(str).to_numpy(),
        df["sku7"].astype(str).to_numpy(), df["taglia"].astype(str).to_numpy(),
        df["genere"].astype(str).to_numpy(), df["acquirente"].astype(str).to_numpy(),
        df["paiaSpedite"].astype(float).to_numpy(), df["nettoSpedito"].astype(float).to_numpy(),
        df["lordoSpedito"].astype(float).to_numpy(),
        _fmt_date_series(df["dataVendita"]), _fmt_date_series(df["dataReso"]),
        df["ordineId"].astype(str).to_numpy(), df["rigaOrdine"].astype(str).to_numpy(),
        df["tipoSpedizione"].astype(str).to_numpy(), df["isPromo"].astype(bool).astype(int).tolist(),
        status, [is_rimborso_extra] * n, matched_via_list,
        [fonte_file] * n, [now] * n,
    ))


_INSERT_SQL = (
    "INSERT OR IGNORE INTO righe (id, key_ordine, key_composito, mkp, nazione, clz_originale, "
    "clz_mappata, sku_full, sku13, sku7, taglia, genere, acquirente, paia_spedite, netto_spedito, "
    "lordo_spedito, data_vendita, data_reso, ordine_id, riga_ordine, tipo_spedizione, is_promo, "
    "status, is_rimborso_extra, matched_via, fonte_file, caricato_il) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _executemany_chunked(conn: sqlite3.Connection, sql: str, records: list, chunk_size: int = 20000,
                          progress: "Callable | None" = None):
    """INSERT a blocchi invece che in un'unica executemany gigante: tiene bassa la RAM di picco
    (non serve costruire/tenere l'intera lista in un colpo solo lato SQLite) e permette di
    mostrare un progresso su file molto grandi invece di un'attesa "muta"."""
    n = len(records)
    for i in range(0, n, chunk_size):
        conn.executemany(sql, records[i:i + chunk_size])
        if progress:
            progress(min(i + chunk_size, n), n)


# --------------------------------------------------------------------------------------
# Lookup FIFO per upsert_resi
# --------------------------------------------------------------------------------------

def _index_tutti(conn: sqlite3.Connection, col: str, keys) -> dict:
    """Indice FIFO su TUTTE le righe (Spedito E Reso), ordinate per rowid:
    {chiave: deque[(id, status)]}.

    Includere anche le righe già 'Reso' è ciò che rende il ricarico RESI idempotente: un reso
    già applicato ritrova la sua riga (ormai 'Reso') e viene registrato come duplicato, invece
    di non trovare nulla e convertire per sbaglio un'altra riga 'Spedito' mai restituita.
    (La versione precedente filtrava WHERE status='Spedito': era quella a nascondere il
    partner già convertito durante il ricarico.)
    """
    idx: dict[str, deque] = {}
    cur = conn.cursor()
    for chunk in _chunked(list(set(keys))):
        placeholders = ",".join("?" * len(chunk))
        q = f"SELECT id, {col}, status FROM righe WHERE {col} IN ({placeholders}) ORDER BY rowid"
        for row_id, k, status in cur.execute(q, chunk):
            idx.setdefault(k, deque()).append((row_id, status))
    return idx


def _pop_fifo(idx: dict, key: str, consumed_now: set) -> tuple[str | None, str | None]:
    """Sfila il primo candidato non ancora consumato in questo upload per la chiave data.
    NON salta le righe già 'Reso': la decisione converti/no-op spetta al chiamante
    (regola: già Reso -> duplicato/no-op; Spedito -> converti)."""
    bucket = idx.get(key)
    if not bucket:
        return None, None
    while bucket:
        cand_id, cand_status = bucket.popleft()
        if cand_id not in consumed_now:
            return cand_id, cand_status
    return None, None


# --------------------------------------------------------------------------------------
# Upload DATASET
# --------------------------------------------------------------------------------------

def _unisci_resi_senza_ordine(conn: sqlite3.Connection, key_ordine, key_composito, row_id) -> set[int]:
    """Abbina le righe del DATASET ai resi caricati prima dell'ordine (is_rimborso_extra=1), con la
    stessa cascata di upsert_resi (ordine+riga+sku+taglia, poi chiave composita; FIFO). Le righe
    abbinate cambiano id e tornano righe normali. Ritorna le posizioni del DATASET da NON inserire."""
    if conn.execute("SELECT 1 FROM righe WHERE is_rimborso_extra=1 LIMIT 1").fetchone() is None:
        return set()

    def indice(col: str, keys) -> dict:
        idx: dict[str, deque] = {}
        for chunk in _chunked(list(set(keys))):
            q = (f"SELECT id, {col} FROM righe WHERE is_rimborso_extra=1 AND {col} IN "
                 f"({','.join('?' * len(chunk))}) ORDER BY rowid")
            for rid, k in conn.execute(q, chunk):
                idx.setdefault(k, deque()).append(rid)
        return idx

    saltare: set[int] = set()
    coppie: list[tuple[str, str]] = []          # (id nuovo, id esistente)
    usati: set[str] = set()
    for col, keys in (("key_ordine", key_ordine), ("key_composito", key_composito)):
        idx = indice(col, [k for i, k in enumerate(keys) if i not in saltare])
        for j, k in enumerate(keys):
            if j in saltare:
                continue
            bucket = idx.get(k)
            while bucket:
                cand = bucket.popleft()
                if cand not in usati:
                    usati.add(cand)
                    saltare.add(j)
                    coppie.append((row_id[j], cand))
                    break
    if coppie:
        conn.executemany("UPDATE OR IGNORE righe SET id=?, is_rimborso_extra=0 WHERE id=?", coppie)
    return saltare


def upsert_dataset(conn: sqlite3.Connection, df: pd.DataFrame, fonte_file: str, progress=None) -> dict:
    """df = output di engine.process_dataset() su un file DATASET. Ritorna statistiche upload.

    L'id di ogni riga (hash contenuto + occorrenza) dipende SOLO dal contenuto del file
    corrente (non da quante righe con lo stesso hash sono già nel DB): questo è ciò che
    garantisce che ricaricare lo STESSO file produca sempre esattamente gli stessi id, e
    quindi un idempotente no-op via INSERT OR IGNORE. Sommare un offset basato sullo stato
    attuale del DB romperebbe l'idempotenza (ogni ricarico genererebbe id sempre nuovi)."""
    if df.empty:
        return {"righe_nel_file": 0, "righe_escluse": 0, "righe_nuove": 0, "righe_gia_presenti": 0}
    df = correzioni.applica_regole_df(conn, df)   # regole di correzione salvate (es. UNITED KIN → GB)
    df, righe_escluse = _filtra_esclusioni_df(conn, df)
    if df.empty:
        return {"righe_nel_file": righe_escluse, "righe_escluse": righe_escluse, "righe_nuove": 0, "righe_gia_presenti": 0}

    key_ordine = _key_ordine_series(df).to_numpy()
    key_composito = _key_composito_series(df).to_numpy()
    content_hash = _content_hash_series(df)
    occurrence = content_hash.groupby(content_hash).cumcount()
    row_id = (content_hash + "#" + occurrence.astype(str)).to_numpy()

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    status = np.where(df["isReso"].to_numpy(), "Reso", "Spedito")
    records = _build_records(df, row_id, key_ordine, key_composito, status, 0, None, fonte_file, now)

    # Un reso caricato PRIMA del suo ordine è già una riga completa (vendita + reso, con le sue
    # date): quando arriva il DATASET con quell'ordine non va inserita una seconda riga, altrimenti
    # la vendita sarebbe contata due volte. La riga esistente prende l'id della riga del DATASET
    # (così il ricarico dello stesso file resta idempotente) e smette di essere "senza ordine".
    saltare = _unisci_resi_senza_ordine(conn, key_ordine, key_composito, row_id)
    if saltare:
        records = [r for i, r in enumerate(records) if i not in saltare]

    prima = conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0]
    _executemany_chunked(conn, _INSERT_SQL, records, progress=progress)
    dopo = conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0]
    nuove = dopo - prima
    stats = {
        "righe_nel_file": len(df) + righe_escluse,
        "righe_escluse": righe_escluse,
        "righe_nuove": nuove,
        "righe_gia_presenti": len(df) - nuove,
    }
    conn.execute(
        "INSERT INTO upload_log (ts, fonte_file, tipo, righe_nel_file, righe_nuove, righe_gia_presenti) "
        "VALUES (?,?,?,?,?,?)",
        (now, fonte_file, "DATASET", stats["righe_nel_file"], stats["righe_nuove"], stats["righe_gia_presenti"]),
    )
    conn.commit()
    return stats


# --------------------------------------------------------------------------------------
# Upload RESI — cascata a due stadi, su TUTTE le righe (Spedito e Reso)
# --------------------------------------------------------------------------------------

def upsert_resi(conn: sqlite3.Connection, df: pd.DataFrame, fonte_file: str, progress=None) -> dict:
    """df = output di engine.process_dataset() su un file RESI.

    Regola di match (due stadi, su TUTTE le righe — Spedito e Reso):
      1. ordine|riga|sku13|taglia
      2. mkp|nazione|acquirente|sku13|taglia|lordo_in_centesimi
    Riga trovata e già 'Reso'  -> duplicato, NO-OP (rende il ricarico idempotente).
    Riga trovata e 'Spedito'   -> UPDATE a 'Reso' con data_reso e matched_via.
    Nessuna riga (a nessuno stato) con nessuna delle due chiavi -> INSERT del reso come ordine
    reale (vendita + reso con le date del file), is_rimborso_extra=1.
    """
    esito = {"convertiti": 0, "duplicati": 0, "senza_ordine": 0, "righe_escluse": 0}
    if df.empty:
        return esito
    df = correzioni.applica_regole_df(conn, df)   # stesse regole del DATASET: le chiavi di match restano coerenti
    df, righe_escluse = _filtra_esclusioni_df(conn, df)
    esito["righe_escluse"] = righe_escluse
    if df.empty:
        return esito

    key_ordine_resi = _key_ordine_series(df).to_numpy()
    key_composito_resi = _key_composito_series(df).to_numpy()
    data_reso_fmt = _fmt_date_series(df["dataReso"])  # precomputato una volta, non per-riga in loop
    n = len(df)
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    log_rows = []

    ordine_id_arr = df["ordineId"].to_numpy()
    sku13_arr = df["sku13"].to_numpy()

    matched_ids: list[str] = []
    matched_modalita: list[str] = []
    matched_data_reso: list[str | None] = []
    remaining_positions: list[int] = []
    senza_ordine_positions: list[int] = []
    consumed_now: set[str] = set()

    def _duplicato(j: int, k_comp: str, modalita: str):
        esito["duplicati"] += 1
        log_rows.append((now, fonte_file, "duplicato", str(ordine_id_arr[j]),
                          str(ordine_id_arr[j]), str(sku13_arr[j]), k_comp, modalita))

    # --- Stage 1: ordine|riga|sku13|taglia, su TUTTE le righe (Spedito e Reso) ---
    idx_ordine = _index_tutti(conn, "key_ordine", key_ordine_resi)
    for j in range(n):
        row_id, status = _pop_fifo(idx_ordine, key_ordine_resi[j], consumed_now)
        if row_id is None:
            remaining_positions.append(j)
        else:
            consumed_now.add(row_id)
            if status == "Reso":
                _duplicato(j, key_ordine_resi[j], "ORDINE+RIGA+SKU+TG")
            else:
                matched_ids.append(row_id)
                matched_modalita.append("ORDINE+RIGA+SKU+TG")
                matched_data_reso.append(data_reso_fmt[j])
        if progress and j % 20000 == 0:
            progress(j, n, "match ordine")

    # --- Stage 2: composito, su TUTTE le righe (Spedito e Reso) ---
    if remaining_positions:
        idx_comp = _index_tutti(conn, "key_composito", key_composito_resi[remaining_positions])
        for pos, j in enumerate(remaining_positions):
            k_comp = key_composito_resi[j]
            row_id, status = _pop_fifo(idx_comp, k_comp, consumed_now)
            if row_id is None:
                # nessuna riga nel DB (a qualunque stato) con queste chiavi: reso senza spedito noto
                senza_ordine_positions.append(j)
            else:
                consumed_now.add(row_id)
                if status == "Reso":
                    _duplicato(j, k_comp, "MKP+NAZ+ACQUIRENTE+SKU+TG+IMPORTO")
                else:
                    matched_ids.append(row_id)
                    matched_modalita.append("MKP+NAZ+ACQUIRENTE+SKU+TG+IMPORTO")
                    matched_data_reso.append(data_reso_fmt[j])
            if progress and pos % 20000 == 0:
                progress(pos, len(remaining_positions), "match composito")

    # --- UPDATE vettoriale delle righe convertite (a blocchi) ---
    if matched_ids:
        _executemany_chunked(
            conn, "UPDATE righe SET status='Reso', data_reso=?, matched_via=? WHERE id=?",
            list(zip(matched_data_reso, matched_modalita, matched_ids)), progress=progress,
        )
        for rid, mv in zip(matched_ids, matched_modalita):
            log_rows.append((now, fonte_file, "convertito", None, None, None, None, mv))
        esito["convertiti"] = len(matched_ids)

    # --- INSERT dei resi senza ordine nel DB ---
    if senza_ordine_positions:
        st = df.iloc[senza_ordine_positions].reset_index(drop=True)
        st_key_ordine = key_ordine_resi[senza_ordine_positions]
        st_key_comp = key_composito_resi[senza_ordine_positions]
        st_hash = _content_hash_series(st)
        occ = st_hash.groupby(st_hash).cumcount()
        st_id = ("REXTRA-" + st_hash + "#" + occ.astype(str)).to_numpy()

        records = _build_records(st, st_id, st_key_ordine, st_key_comp, ["Reso"] * len(st), 1,
                                  "SENZA_ORDINE", fonte_file, now)
        st_ordine_id = st["ordineId"].to_numpy()
        st_sku13 = st["sku13"].to_numpy()
        log_rows.extend(
            (now, fonte_file, "senza_ordine", oid, oid, str(sku), kcomp, "SENZA_ORDINE")
            for oid, sku, kcomp in zip(st_ordine_id, st_sku13, st_key_comp)
        )
        _executemany_chunked(conn, _INSERT_SQL, records, progress=progress)
        esito["senza_ordine"] = len(senza_ordine_positions)

    if log_rows:
        conn.executemany(
            "INSERT INTO log_match (ts, fonte_file, esito, ordine_id, ordine_id_resi, sku13, key_comp, modalita) "
            "VALUES (?,?,?,?,?,?,?,?)", log_rows,
        )
    conn.execute(
        "INSERT INTO upload_log (ts, fonte_file, tipo, righe_nel_file, convertiti, duplicati, standalone) "
        "VALUES (?,?,?,?,?,?,?)",
        (now, fonte_file, "RESI", len(df), esito["convertiti"], esito["duplicati"], esito["senza_ordine"]),
    )
    conn.commit()
    return esito


# --------------------------------------------------------------------------------------
# Query per range di date: ritorna DataFrame nella stessa forma
# prodotta da engine.process_dataset(), pronti per metrics.py / report_builders.py invariati.
# --------------------------------------------------------------------------------------

_SELECT_COLS = (
    "id, mkp, nazione, clz_originale, clz_mappata, sku_full, sku13, sku7, taglia, genere, "
    "acquirente, paia_spedite, netto_spedito, lordo_spedito, data_vendita, data_reso, "
    "ordine_id, riga_ordine, tipo_spedizione, is_promo, status, is_rimborso_extra, matched_via"
)

_RENAME = {
    "clz_originale": "clzOriginale", "clz_mappata": "clzMappata", "sku_full": "skuFull",
    "ordine_id": "ordineId", "riga_ordine": "rigaOrdine", "tipo_spedizione": "tipoSpedizione",
    "is_promo": "isPromo", "matched_via": "matchedVia",
}


def _rows_to_df(rows, cols) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=cols)
    df = df.rename(columns=_RENAME)
    if df.empty:
        # le pagine usano .dt sulle date anche quando il DataFrame è vuoto (es. nessun reso fuori periodo)
        df["dataVendita"] = pd.Series(dtype="datetime64[ns]")
        df["dataReso"] = pd.Series(dtype="datetime64[ns]")
        return df
    df["dataVendita"] = pd.to_datetime(df["data_vendita"], errors="coerce")
    df["dataReso"] = pd.to_datetime(df["data_reso"], errors="coerce")
    df["isPromo"] = df["isPromo"].map(lambda x: int.from_bytes(x, "little") != 0 if isinstance(x, (bytes, bytearray)) else bool(x))
    for c in ("mkp", "nazione", "clzMappata", "taglia", "genere", "tipoSpedizione"):
        df[c] = df[c].astype("category")
    return df


def _finalize_period_df(df: pd.DataFrame, period_start, period_end) -> pd.DataFrame:
    """Applica la semantica 'reso conta solo se data_reso è nello stesso periodo' (applicata a
    query-time) e ricostruisce le colonne derivate che
    report_builders/metrics si aspettano."""
    if df.empty:
        for c in ("paiaSpedite", "paiaRese", "paiaNette", "nettoSpedito", "nettoReso", "nettoNetto",
                   "lordoSpedito", "lordoReso", "lordoNetto", "isReso", "lordoEUR", "nettoEUR", "qta"):
            df[c] = pd.Series(dtype="float64")
        return df

    reso_in_periodo = df["dataReso"].apply(lambda d: pd.notna(d) and period_start <= d <= period_end)
    is_reso_eff = (df["status"] == "Reso") & reso_in_periodo

    df["paiaSpedite"] = df["paia_spedite"]
    df["paiaRese"] = df["paia_spedite"].where(is_reso_eff, 0.0)
    df["paiaNette"] = df["paiaSpedite"] - df["paiaRese"]
    df["nettoSpedito"] = df["netto_spedito"]
    df["nettoReso"] = df["netto_spedito"].where(is_reso_eff, 0.0)
    df["nettoNetto"] = df["nettoSpedito"] - df["nettoReso"]
    df["lordoSpedito"] = df["lordo_spedito"]
    df["lordoReso"] = df["lordo_spedito"].where(is_reso_eff, 0.0)
    df["lordoNetto"] = df["lordoSpedito"] - df["lordoReso"]
    df["lordoEUR"] = df["lordoNetto"]
    df["nettoEUR"] = df["nettoNetto"]
    df["qta"] = df["paiaNette"]
    df["isReso"] = is_reso_eff
    return df.drop(columns=["data_vendita", "data_reso", "paia_spedite", "netto_spedito",
                             "lordo_spedito", "status", "is_rimborso_extra"])


def query_period(conn: sqlite3.Connection, start, end, perimetro: str = "1",
                 sku_prefix: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ritorna (venduto_df, resi_fuori_periodo_df) per il periodo [start, end] (date incluse).
    `venduto_df` ha ESATTAMENTE la forma prodotta da engine.process_dataset(): può essere
    passato invariato a metrics.py/report_builders.py. `resi_fuori_periodo_df` raccoglie i resi del periodo
    di vendite non appartenenti al periodo; è il secondo argomento di metrics.compute_channel_kpi."""
    start_s, end_s = _fmt_date(start), _fmt_date(end)
    period_start, period_end = pd.Timestamp(start), pd.Timestamp(end)

    where_perimetro = ""
    if perimetro == "2":
        where_perimetro = " AND tipo_spedizione='DIRETTO'"
    elif perimetro == "3":
        where_perimetro = " AND tipo_spedizione='ESTERNA'"

    # filtro SKU per prefisso (solo lettere/cifre, quindi sicuro per LIKE): sku13 = SKU senza
    # trattini, primi 13 caratteri; per prefissi più lunghi si confronta l'SKU completo senza trattini.
    params_sku: tuple = ()
    if sku_prefix:
        campo = "sku13" if len(sku_prefix) <= 13 else "REPLACE(sku_full, '-', '')"
        where_perimetro += f" AND {campo} LIKE ?"
        params_sku = (sku_prefix + "%",)

    q_venduto = (f"SELECT {_SELECT_COLS} FROM righe WHERE data_vendita BETWEEN ? AND ?{where_perimetro}")
    rows_v = conn.execute(q_venduto, (start_s, end_s) + params_sku).fetchall()
    venduto = _rows_to_df(rows_v, _SELECT_COLS.split(", "))
    venduto = _finalize_period_df(venduto, period_start, period_end)

    # Resi fuori periodo: data_reso nel range e vendita NON nel range. Un reso caricato senza il
    # suo ordine è un ordine reale (ha la sua data vendita): segue le stesse regole di tutti.
    q_reso_extra = (f"SELECT {_SELECT_COLS} FROM righe WHERE status='Reso' AND data_reso BETWEEN ? AND ? "
                     f"AND (data_vendita IS NULL OR data_vendita < ? OR data_vendita > ?)"
                     f"{where_perimetro}")
    rows_r = conn.execute(q_reso_extra, (start_s, end_s, start_s, end_s) + params_sku).fetchall()
    reso_extra = _rows_to_df(rows_r, _SELECT_COLS.split(", "))
    if not reso_extra.empty:
        # per i resi fuori periodo tutto l'importo diventa "reso" a prescindere dal range: è
        # interamente un decremento del Fatturato del periodo.
        reso_extra["paiaSpedite"] = 0.0
        reso_extra["paiaRese"] = reso_extra["paia_spedite"]
        reso_extra["paiaNette"] = -reso_extra["paia_spedite"]
        reso_extra["nettoSpedito"] = 0.0
        reso_extra["nettoReso"] = reso_extra["netto_spedito"]
        reso_extra["nettoNetto"] = -reso_extra["netto_spedito"]
        reso_extra["lordoSpedito"] = 0.0
        reso_extra["lordoReso"] = reso_extra["lordo_spedito"]
        reso_extra["lordoNetto"] = -reso_extra["lordo_spedito"]
        reso_extra["lordoEUR"] = reso_extra["lordoNetto"]
        reso_extra["nettoEUR"] = reso_extra["nettoNetto"]
        reso_extra["qta"] = reso_extra["paiaNette"]
        reso_extra["isReso"] = True
        reso_extra = reso_extra.drop(columns=["data_vendita", "data_reso", "paia_spedite",
                                               "netto_spedito", "lordo_spedito", "status", "is_rimborso_extra"])
    else:
        reso_extra = _finalize_period_df(reso_extra, period_start, period_end)

    return venduto.reset_index(drop=True), reso_extra.reset_index(drop=True)


def get_data_bounds(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    row = conn.execute("SELECT MIN(data_vendita), MAX(data_vendita) FROM righe").fetchone()
    return row[0], row[1]


def get_upload_log(conn: sqlite3.Connection, limit: int = 200) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT ts, fonte_file, tipo, righe_nel_file, righe_nuove, righe_gia_presenti, "
        "convertiti, duplicati, standalone AS senza_ordine FROM upload_log ORDER BY ts DESC LIMIT ?",
        conn, params=(limit,))


def get_match_log(conn: sqlite3.Connection, fonte_file: str | None = None, esito: str | None = None,
                   limit: int = 1000) -> pd.DataFrame:
    q = "SELECT ts, fonte_file, esito, ordine_id, ordine_id_resi, sku13, key_comp, modalita FROM log_match WHERE 1=1"
    params: list = []
    if fonte_file:
        q += " AND fonte_file = ?"
        params.append(fonte_file)
    if esito == "senza_ordine":     # "standalone" è il nome con cui i caricamenti precedenti l'hanno salvato
        q += " AND esito IN ('senza_ordine', 'standalone')"
    elif esito:
        q += " AND esito = ?"
        params.append(esito)
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    return pd.read_sql_query(q, conn, params=params)


def get_stats(conn: sqlite3.Connection) -> dict:
    tot = conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0]
    spediti = conn.execute("SELECT COUNT(*) FROM righe WHERE status='Spedito'").fetchone()[0]
    resi = conn.execute("SELECT COUNT(*) FROM righe WHERE status='Reso'").fetchone()[0]
    senza_ordine = conn.execute("SELECT COUNT(*) FROM righe WHERE is_rimborso_extra=1").fetchone()[0]
    start, end = get_data_bounds(conn)
    anag_tot = conn.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0]
    anag_modelli = conn.execute("SELECT COUNT(DISTINCT sku7) FROM anagrafica").fetchone()[0]
    return {
        "righe_totali": tot, "spediti": spediti, "resi": resi, "resi_senza_ordine": senza_ordine,
        "data_min": start, "data_max": end,
        "anagrafica_totale": anag_tot, "anagrafica_modelli": anag_modelli,
    }


# --------------------------------------------------------------------------------------
# Gestione persistenza Anagrafica (Articoli, SKU13, Descrizioni, Brand, Genere)
# --------------------------------------------------------------------------------------

_UPSERT_ANAGRAFICA_SQL = """
INSERT INTO anagrafica (
    sku13, sku7, brand_cod, brand, linea_cod, linea, reparto_cod,
    tipo_cod, categoria, descrizione, fondo_cod, fondo_desc,
    colore_cod, colore_desc, taglia_base, valore, data_disponibilita,
    flag, stagione, semestre, genere, fonte_file, aggiornato_il
) VALUES (
    :sku13, :sku7, :brand_cod, :brand, :linea_cod, :linea, :reparto_cod,
    :tipo_cod, :categoria, :descrizione, :fondo_cod, :fondo_desc,
    :colore_cod, :colore_desc, :taglia_base, :valore, :data_disponibilita,
    :flag, :stagione, :semestre, :genere, :fonte_file, :aggiornato_il
)
ON CONFLICT(sku13) DO UPDATE SET
    sku7=excluded.sku7,
    brand_cod=excluded.brand_cod,
    brand=excluded.brand,
    linea_cod=excluded.linea_cod,
    linea=excluded.linea,
    reparto_cod=excluded.reparto_cod,
    tipo_cod=excluded.tipo_cod,
    categoria=excluded.categoria,
    descrizione=excluded.descrizione,
    fondo_cod=excluded.fondo_cod,
    fondo_desc=excluded.fondo_desc,
    colore_cod=excluded.colore_cod,
    colore_desc=excluded.colore_desc,
    taglia_base=excluded.taglia_base,
    valore=excluded.valore,
    data_disponibilita=excluded.data_disponibilita,
    flag=excluded.flag,
    stagione=excluded.stagione,
    semestre=excluded.semestre,
    genere=excluded.genere,
    fonte_file=excluded.fonte_file,
    aggiornato_il=excluded.aggiornato_il
"""


def upsert_anagrafica(conn: sqlite3.Connection, records: list[dict], fonte_file: str,
                      progress=None, applica_esclusioni: bool = True) -> dict:
    """Carica o aggiorna i record anagrafica nel DB SQLite.
    Se un articolo (identificato da sku13) è già presente nel DB (ad es. da un file precedente),
    i suoi dati vengono interamente aggiornati e sostituiti con quelli del nuovo file.
    Gli articoli che violano le regole di esclusione attive (marchi e categorie) vengono scartati e non importati.
    """
    righe_nel_file = len(records) if records else 0
    righe_escluse = 0

    if applica_esclusioni and records:
        escl = get_esclusioni_anagrafica(conn)
        marchi_escl = escl["marchi"]
        cat_escl = escl["categorie"]
        if marchi_escl or cat_escl:
            valid_records = []
            for r in records:
                b = str(r.get("brand", "")).upper().strip()
                c = str(r.get("categoria", "")).strip()
                if b in marchi_escl or c in cat_escl:
                    righe_escluse += 1
                else:
                    valid_records.append(r)
            records = valid_records

    if not records:
        tot = conn.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0]
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        if righe_nel_file > 0:
            conn.execute(
                "INSERT INTO upload_log (ts, fonte_file, tipo, righe_nel_file, righe_nuove, righe_gia_presenti, convertiti, duplicati, standalone) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (now, fonte_file, "ANAGRAFICA", righe_nel_file, 0, 0, righe_escluse, 0, 0),
            )
            conn.commit()
        return {
            "righe_nel_file": righe_nel_file,
            "righe_escluse": righe_escluse,
            "righe_nuove": 0,
            "righe_aggiornate": 0,
            "totale_articoli": tot,
        }

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    default_fields = {
        "sku13": "", "sku7": "", "brand_cod": "", "brand": "", "linea_cod": "", "linea": "",
        "reparto_cod": "", "tipo_cod": "", "categoria": "", "descrizione": "",
        "fondo_cod": "", "fondo_desc": "", "colore_cod": "", "colore_desc": "",
        "taglia_base": "", "valore": "", "data_disponibilita": "", "flag": "",
        "stagione": "", "semestre": "", "genere": "NON CLASSIFICATO",
        "fonte_file": fonte_file, "aggiornato_il": now,
    }
    records = [{**default_fields, **r} for r in records]

    keys = list({r["sku13"] for r in records if r.get("sku13")})
    cur = conn.cursor()
    existing = set()
    for chunk in _chunked(keys, 500):
        placeholders = ",".join("?" * len(chunk))
        q = f"SELECT sku13 FROM anagrafica WHERE sku13 IN ({placeholders})"
        for row in cur.execute(q, chunk):
            existing.add(row[0])

    nuove = sum(1 for k in keys if k not in existing)
    aggiornate = sum(1 for k in keys if k in existing)

    n = len(records)
    chunk_size = 5000
    for i in range(0, n, chunk_size):
        chunk = records[i:i + chunk_size]
        cur.executemany(_UPSERT_ANAGRAFICA_SQL, chunk)
        if progress:
            progress(min(i + chunk_size, n), n, "scrittura anagrafica")

    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO upload_log (ts, fonte_file, tipo, righe_nel_file, righe_nuove, righe_gia_presenti, convertiti, duplicati, standalone) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (now, fonte_file, "ANAGRAFICA", righe_nel_file, nuove, aggiornate, righe_escluse, 0, 0),
    )
    conn.commit()

    tot = cur.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0]
    return {
        "righe_nel_file": righe_nel_file,
        "righe_escluse": righe_escluse,
        "righe_nuove": nuove,
        "righe_aggiornate": aggiornate,
        "totale_articoli": tot,
    }


def get_anagrafica_dict(conn: sqlite3.Connection) -> dict[str, dict]:
    """Ritorna l'anagrafica dal DB sotto forma di dizionario indicizzato per SKU13 e per SKU7 (codice articolo):
    {
        chiave: {
            'desc': ..., 'modello': ..., 'clz': ..., 'serie': ..., 'genere': ...,
            'materiale': ..., 'colore': ..., 'taglia_base': ..., 'stagione': ...,
            'cod': ..., 'sku': ...
        }
    }
    Compatibile al 100% con i report esistenti (top_articoli_dashboard, top_articoli_y2y, comparativa_codici, sellthrough, ecc.).
    """
    cur = conn.cursor()
    try:
        escl = get_esclusioni_anagrafica(conn)
        rows = cur.execute(
            "SELECT sku13, sku7, brand, linea, categoria, descrizione, fondo_desc, colore_desc, taglia_base, stagione, semestre, genere "
            "FROM anagrafica"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}

    anag: dict[str, dict] = {}
    for sku13, sku7, brand, linea, cat, desc, f_desc, c_desc, t_base, stag, sem, genere in rows:
        desc_val = desc or "-"
        stag_val = f"{stag}/{sem}" if sem else (stag or "")
        b_clean = (brand or "").upper().strip()
        cat_clean = (cat or "").strip()
        is_escluso = (b_clean in escl["marchi"]) or (cat_clean in escl["categorie"])
        entry = {
            "desc": desc_val,
            "modello": desc_val,
            "clz": brand or "-",
            "serie": linea or "-",
            "categoria": cat_clean,
            "genere": genere or "NON CLASSIFICATO",
            "materiale": f_desc or "",
            "colore": c_desc or "",
            "taglia_base": t_base or "",
            "stagione": stag_val,
            "cod": sku7 or "",
            "sku": sku13 or "",
            "escluso": is_escluso,
        }
        if sku13:
            anag[sku13] = entry
        if sku7 and (sku7 not in anag or (anag[sku7].get("genere") == "NON CLASSIFICATO" and entry["genere"] != "NON CLASSIFICATO")):
            anag[sku7] = entry

    return anag


def get_anagrafica_stats(conn: sqlite3.Connection) -> dict:
    """Ritorna statistiche aggregate sull'anagrafica memorizzata nel DB."""
    try:
        tot_sku13 = conn.execute("SELECT COUNT(*) FROM anagrafica").fetchone()[0]
        if tot_sku13 == 0:
            return {
                "totale_sku13": 0, "totale_sku7": 0, "per_brand": {}, "per_genere": {},
                "ultimo_aggiornamento": None, "fonti_file": [],
            }
        tot_sku7 = conn.execute("SELECT COUNT(DISTINCT sku7) FROM anagrafica").fetchone()[0]
        ultimo = conn.execute("SELECT MAX(aggiornato_il) FROM anagrafica").fetchone()[0]
        fonti = [r[0] for r in conn.execute("SELECT DISTINCT fonte_file FROM anagrafica WHERE fonte_file IS NOT NULL").fetchall()]
        per_brand = dict(conn.execute("SELECT brand, COUNT(*) FROM anagrafica GROUP BY brand ORDER BY COUNT(*) DESC").fetchall())
        per_genere = dict(conn.execute("SELECT genere, COUNT(*) FROM anagrafica GROUP BY genere ORDER BY COUNT(*) DESC").fetchall())
        return {
            "totale_sku13": tot_sku13,
            "totale_sku7": tot_sku7,
            "per_brand": per_brand,
            "per_genere": per_genere,
            "ultimo_aggiornamento": ultimo,
            "fonti_file": fonti,
        }
    except sqlite3.OperationalError:
        return {
            "totale_sku13": 0, "totale_sku7": 0, "per_brand": {}, "per_genere": {},
            "ultimo_aggiornamento": None, "fonti_file": [],
        }


def sincronizza_genere_righe(conn: sqlite3.Connection) -> int:
    """Aggiorna la colonna genere delle righe vendite/resi nel DB associandola al genere presente in anagrafica.
    Usa gli indici su sku13 e sku7 per la massima velocità. Ritorna il numero di righe modificate.
    """
    cur = conn.cursor()
    # 1. Match esatto per sku13
    cur.execute("""
        UPDATE righe
        SET genere = (SELECT anagrafica.genere FROM anagrafica WHERE anagrafica.sku13 = righe.sku13)
        WHERE (righe.genere = 'NON CLASSIFICATO' OR righe.genere = '' OR righe.genere IS NULL)
          AND righe.sku13 IN (
              SELECT anagrafica.sku13 FROM anagrafica
              WHERE anagrafica.genere != 'NON CLASSIFICATO' AND anagrafica.genere != ''
          )
    """)
    n1 = cur.rowcount

    # 2. Match di fallback per sku7 per le righe ancora non classificate
    cur.execute("""
        UPDATE righe
        SET genere = (
            SELECT anagrafica.genere FROM anagrafica
            WHERE anagrafica.sku7 = righe.sku7 AND anagrafica.genere != 'NON CLASSIFICATO' AND anagrafica.genere != ''
            LIMIT 1
        )
        WHERE (righe.genere = 'NON CLASSIFICATO' OR righe.genere = '' OR righe.genere IS NULL)
          AND righe.sku7 IN (
              SELECT anagrafica.sku7 FROM anagrafica
              WHERE anagrafica.genere != 'NON CLASSIFICATO' AND anagrafica.genere != ''
          )
    """)
    n2 = cur.rowcount
    conn.commit()
    return n1 + n2


def svuota_anagrafica(conn: sqlite3.Connection) -> None:
    """Elimina tutti i record dalla tabella anagrafica nel DB senza toccare le righe di vendite e resi."""
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    conn.execute("DELETE FROM anagrafica;")
    conn.execute(
        "INSERT INTO upload_log (ts, fonte_file, tipo, righe_nel_file, righe_nuove, righe_gia_presenti, convertiti, duplicati, standalone) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (now, "SVUOTA_ANAGRAFICA", "ANAGRAFICA", 0, 0, 0, 0, 0, 0),
    )
    conn.commit()


# ---------------------------------------------------------------------------------------
# REGOLE ANAGRAFICA (Esclusione marchi, categorie, correzioni mirate)
# ---------------------------------------------------------------------------------------

def get_regole_anagrafica(conn: sqlite3.Connection) -> list[dict]:
    """Ritorna la lista di tutte le regole registrate per l'anagrafica."""
    try:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, tipo, valore, attivo, note, creato_il "
            "FROM regole_anagrafica ORDER BY tipo ASC, valore ASC"
        ).fetchall()
        return [
            {
                "id": r[0], "tipo": r[1], "valore": r[2],
                "attivo": bool(r[3]), "note": r[4] or "", "creato_il": r[5]
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []


def salva_regola_anagrafica(conn: sqlite3.Connection, tipo: str, valore: str,
                            attivo: int = 1, note: str = "") -> int:
    """Inserisce o aggiorna una regola di anagrafica (es. escludi_marchio, escludi_categoria)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    val = valore.strip()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO regole_anagrafica (tipo, valore, attivo, note, creato_il)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(tipo, valore) DO UPDATE SET
            attivo = excluded.attivo,
            note = excluded.note
    """, (tipo, val, int(attivo), note.strip(), now))
    conn.commit()
    return cur.lastrowid or 0


def elimina_regola_anagrafica(conn: sqlite3.Connection, id_regola: int) -> bool:
    """Elimina definitivamente una regola di anagrafica."""
    cur = conn.cursor()
    cur.execute("DELETE FROM regole_anagrafica WHERE id = ?", (id_regola,))
    conn.commit()
    return cur.rowcount > 0


def attiva_disattiva_regola_anagrafica(conn: sqlite3.Connection, id_regola: int, attivo: bool) -> bool:
    """Attiva o disattiva una regola di anagrafica."""
    cur = conn.cursor()
    cur.execute("UPDATE regole_anagrafica SET attivo = ? WHERE id = ?", (1 if attivo else 0, id_regola))
    conn.commit()
    return cur.rowcount > 0


def get_esclusioni_anagrafica(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Ritorna i set dei marchi e delle categorie esclusi dalle regole attive."""
    regole = get_regole_anagrafica(conn)
    marchi: set[str] = set()
    categorie: set[str] = set()
    for r in regole:
        if not r["attivo"]:
            continue
        if r["tipo"] == "escludi_marchio":
            marchi.add(r["valore"].upper().strip())
        elif r["tipo"] == "escludi_categoria":
            categorie.add(r["valore"].strip())
    return {"marchi": marchi, "categorie": categorie}


def get_skus_esclusi_anagrafica(conn: sqlite3.Connection) -> set[str]:
    """Ritorna l'insieme di sku13 e sku7 esclusi secondo le regole attive."""
    escl = get_esclusioni_anagrafica(conn)
    marchi = list(escl["marchi"])
    categorie = list(escl["categorie"])
    if not marchi and not categorie:
        return set()
    clauses = []
    params = []
    if marchi:
        placeholders = ",".join("?" for _ in marchi)
        clauses.append(f"UPPER(TRIM(brand)) IN ({placeholders})")
        params.extend(marchi)
    if categorie:
        placeholders = ",".join("?" for _ in categorie)
        clauses.append(f"TRIM(categoria) IN ({placeholders})")
        params.extend(categorie)
    sql = f"SELECT sku13, sku7 FROM anagrafica WHERE {' OR '.join(clauses)}"
    cur = conn.cursor()
    skus: set[str] = set()
    for s13, s7 in cur.execute(sql, params):
        if s13:
            skus.add(str(s13).strip())
        if s7:
            skus.add(str(s7).strip())
    return skus


def conta_articoli_esclusi_anagrafica(conn: sqlite3.Connection) -> int:
    """Conta quanti articoli attualmente presenti nella tabella anagrafica violano le regole di esclusione attive."""
    escl = get_esclusioni_anagrafica(conn)
    marchi = list(escl["marchi"])
    categorie = list(escl["categorie"])
    if not marchi and not categorie:
        return 0
    clauses = []
    params = []
    if marchi:
        placeholders = ",".join("?" for _ in marchi)
        clauses.append(f"UPPER(TRIM(brand)) IN ({placeholders})")
        params.extend(marchi)
    if categorie:
        placeholders = ",".join("?" for _ in categorie)
        clauses.append(f"TRIM(categoria) IN ({placeholders})")
        params.extend(categorie)
    sql = f"SELECT COUNT(*) FROM anagrafica WHERE {' OR '.join(clauses)}"
    return conn.execute(sql, params).fetchone()[0]


def elimina_articoli_esclusi_anagrafica(conn: sqlite3.Connection) -> int:
    """Elimina dalla tabella anagrafica tutti gli articoli che violano le regole di esclusione attive.
    Ritorna il numero di articoli eliminati.
    """
    escl = get_esclusioni_anagrafica(conn)
    marchi = list(escl["marchi"])
    categorie = list(escl["categorie"])
    if not marchi and not categorie:
        return 0
    clauses = []
    params = []
    if marchi:
        placeholders = ",".join("?" for _ in marchi)
        clauses.append(f"UPPER(TRIM(brand)) IN ({placeholders})")
        params.extend(marchi)
    if categorie:
        placeholders = ",".join("?" for _ in categorie)
        clauses.append(f"TRIM(categoria) IN ({placeholders})")
        params.extend(categorie)
    sql = f"DELETE FROM anagrafica WHERE {' OR '.join(clauses)}"
    cur = conn.cursor()
    cur.execute(sql, params)
    n_del = cur.rowcount
    conn.commit()
    return n_del


def _filtra_esclusioni_df(conn: sqlite3.Connection, df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Filtra le righe del DataFrame che violano le regole di esclusione attive (marchi e categorie)."""
    if df.empty:
        return df, 0
    escl = get_esclusioni_anagrafica(conn)
    marchi_escl = escl["marchi"]
    cat_escl = escl["categorie"]
    if not marchi_escl and not cat_escl:
        return df, 0

    mask_escl = pd.Series(False, index=df.index)
    if marchi_escl:
        if "clzOriginale" in df.columns:
            mask_escl = mask_escl | df["clzOriginale"].astype(str).str.upper().str.strip().isin(marchi_escl)
        if "clzMappata" in df.columns:
            mask_escl = mask_escl | df["clzMappata"].astype(str).str.upper().str.strip().isin(marchi_escl)

    skus_escl = get_skus_esclusi_anagrafica(conn)
    if skus_escl:
        if "sku13" in df.columns:
            mask_escl = mask_escl | df["sku13"].astype(str).isin(skus_escl)
        if "sku7" in df.columns:
            mask_escl = mask_escl | df["sku7"].astype(str).isin(skus_escl)

    n_escluse = int(mask_escl.sum())
    if n_escluse > 0:
        df = df[~mask_escl].reset_index(drop=True)
    return df, n_escluse


def aggiorna_stagione_anagrafica(conn: sqlite3.Connection, sku: str, nuova_stagione: str,
                                aggiorna_sku7: bool = False) -> int:
    """Modifica la stagione (e il semestre se nel formato anno/stagione es. 2026/1)
    di un singolo SKU13 o di tutte le varianti di uno SKU7.
    Ritorna il numero di record aggiornati.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    clean_sku = sku.strip()
    clean_stag = nuova_stagione.strip()

    if "/" in clean_stag:
        parts = clean_stag.split("/", 1)
        stag_val = parts[0].strip()
        sem_val = parts[1].strip()
    else:
        stag_val = clean_stag
        sem_val = ""

    cur = conn.cursor()
    if aggiorna_sku7:
        # Se passato uno sku13 estraiamo lo sku7 (primi 7 caratteri se almeno 7)
        target_sku7 = clean_sku[:7] if len(clean_sku) >= 7 else clean_sku
        cur.execute(
            "UPDATE anagrafica SET stagione = ?, semestre = ?, aggiornato_il = ? WHERE sku7 = ?",
            (stag_val, sem_val, now, target_sku7),
        )
    else:
        cur.execute(
            "UPDATE anagrafica SET stagione = ?, semestre = ?, aggiornato_il = ? WHERE sku13 = ?",
            (stag_val, sem_val, now, clean_sku),
        )
    conn.commit()
    return cur.rowcount


def aggiorna_genere_anagrafica(conn: sqlite3.Connection, sku: str, nuovo_genere: str,
                              aggiorna_sku7: bool = False) -> int:
    """Modifica il genere di un singolo SKU13 o di tutte le varianti di uno SKU7.
    Ritorna il numero di record aggiornati.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    clean_sku = sku.strip()
    clean_gen = nuovo_genere.strip().upper()
    cur = conn.cursor()
    if aggiorna_sku7:
        target_sku7 = clean_sku[:7] if len(clean_sku) >= 7 else clean_sku
        cur.execute(
            "UPDATE anagrafica SET genere = ?, aggiornato_il = ? WHERE sku7 = ?",
            (clean_gen, now, target_sku7),
        )
    else:
        cur.execute(
            "UPDATE anagrafica SET genere = ?, aggiornato_il = ? WHERE sku13 = ?",
            (clean_gen, now, clean_sku),
        )
    conn.commit()
    return cur.rowcount


def ricalcola_tutti_generi(conn: sqlite3.Connection, solo_non_classificati: bool = True) -> dict:
    """Ricalcola il genere degli articoli in anagrafica applicando le regole euristiche avanzate di deduce_genere.
    Se solo_non_classificati è True, valuta soltanto le righe con genere 'NON CLASSIFICATO' o vuoto.
    Ritorna un dizionario con statistiche di aggiornamento.
    """
    from . import engine as eng
    cur = conn.cursor()
    query = (
        "SELECT sku13, brand, linea, reparto_cod, categoria, descrizione, genere "
        "FROM anagrafica "
    )
    if solo_non_classificati:
        query += "WHERE genere = 'NON CLASSIFICATO' OR genere = '' OR genere IS NULL"

    rows = cur.execute(query).fetchall()
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    updates: list[tuple[str, str, str]] = []
    per_genere: dict[str, int] = {}

    for sku13, brand, linea, col6, cat, desc, gen_attuale in rows:
        nuovo_gen = eng.deduce_genere(brand, linea, col6, cat, desc)
        if nuovo_gen != gen_attuale and nuovo_gen != "NON CLASSIFICATO":
            updates.append((nuovo_gen, now, sku13))
            per_genere[nuovo_gen] = per_genere.get(nuovo_gen, 0) + 1

    if updates:
        _executemany_chunked(
            conn,
            "UPDATE anagrafica SET genere = ?, aggiornato_il = ? WHERE sku13 = ?",
            updates,
        )
        conn.commit()

    return {
        "valutati": len(rows),
        "aggiornati": len(updates),
        "per_genere": per_genere,
    }


def get_dettaglio_sku_anagrafica(conn: sqlite3.Connection, sku: str) -> dict | None:
    """Cerca e ritorna i dettagli di uno SKU (cerca prima per sku13 esatto, poi per sku7)."""
    clean = sku.strip()
    if not clean:
        return None
    cur = conn.cursor()
    # 1. Match SKU13 esatto
    row = cur.execute(
        "SELECT sku13, sku7, brand_cod, brand, linea_cod, linea, reparto_cod, tipo_cod, "
        "categoria, descrizione, fondo_cod, fondo_desc, colore_cod, colore_desc, "
        "taglia_base, valore, data_disponibilita, flag, stagione, semestre, genere, "
        "fonte_file, aggiornato_il FROM anagrafica WHERE sku13 = ?",
        (clean,),
    ).fetchone()

    # 2. Match SKU7
    if not row:
        row = cur.execute(
            "SELECT sku13, sku7, brand_cod, brand, linea_cod, linea, reparto_cod, tipo_cod, "
            "categoria, descrizione, fondo_cod, fondo_desc, colore_cod, colore_desc, "
            "taglia_base, valore, data_disponibilita, flag, stagione, semestre, genere, "
            "fonte_file, aggiornato_il FROM anagrafica WHERE sku7 = ? LIMIT 1",
            (clean,),
        ).fetchone()

    if not row:
        return None

    cols = [
        "sku13", "sku7", "brand_cod", "brand", "linea_cod", "linea", "reparto_cod", "tipo_cod",
        "categoria", "descrizione", "fondo_cod", "fondo_desc", "colore_cod", "colore_desc",
        "taglia_base", "valore", "data_disponibilita", "flag", "stagione", "semestre", "genere",
        "fonte_file", "aggiornato_il"
    ]
    res = dict(zip(cols, row))
    stag = res.get("stagione") or ""
    sem = res.get("semestre") or ""
    res["stagione_completa"] = f"{stag}/{sem}" if sem else stag
    return res


