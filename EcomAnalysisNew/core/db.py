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
                    reconciler.py (prima ordine+riga+sku+taglia, poi il composito
                    mkp+naz+acquirente+sku+taglia+importo), su TUTTE le righe (Spedito e Reso):
                    già Reso -> duplicato, no-op; Spedito -> UPDATE a Reso; nessuna riga ->
                    insert standalone (rimborso extra). Includere anche le righe già Reso nella
                    ricerca è ciò che rende il ricarico RESI idempotente.

Query per range di date: "venduto nel periodo" = data_vendita nel range (un reso il cui
data_reso NON è nello stesso range conta come spedito puro per quel periodo); "reso extra nel
periodo" = data_reso nel range ma vendita fuori range (o riga standalone) — feed diretto per
compute_channel_kpi/report_builders, che restano quindi INVARIATI rispetto alla versione a file.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import deque
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

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

CREATE TABLE IF NOT EXISTS log_match (
    ts TEXT, fonte_file TEXT, esito TEXT,
    ordine_id TEXT, ordine_id_resi TEXT, sku13 TEXT, key_comp TEXT, modalita TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_fonte ON log_match(fonte_file);

CREATE TABLE IF NOT EXISTS upload_log (
    ts TEXT, fonte_file TEXT, tipo TEXT, righe_nel_file INTEGER,
    righe_nuove INTEGER, righe_gia_presenti INTEGER,
    convertiti INTEGER, duplicati INTEGER, standalone INTEGER
);
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
    standalone).
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
        df["tipoSpedizione"].astype(str).to_numpy(), df["isPromo"].astype(bool).astype(int).to_numpy(),
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

def upsert_dataset(conn: sqlite3.Connection, df: pd.DataFrame, fonte_file: str, progress=None) -> dict:
    """df = output di engine.process_dataset() su un file DATASET. Ritorna statistiche upload.

    L'id di ogni riga (hash contenuto + occorrenza) dipende SOLO dal contenuto del file
    corrente (non da quante righe con lo stesso hash sono già nel DB): questo è ciò che
    garantisce che ricaricare lo STESSO file produca sempre esattamente gli stessi id, e
    quindi un idempotente no-op via INSERT OR IGNORE. Sommare un offset basato sullo stato
    attuale del DB romperebbe l'idempotenza (ogni ricarico genererebbe id sempre nuovi)."""
    if df.empty:
        return {"righe_nel_file": 0, "righe_nuove": 0, "righe_gia_presenti": 0}

    key_ordine = _key_ordine_series(df).to_numpy()
    key_composito = _key_composito_series(df).to_numpy()
    content_hash = _content_hash_series(df)
    occurrence = content_hash.groupby(content_hash).cumcount()
    row_id = (content_hash + "#" + occurrence.astype(str)).to_numpy()

    now = datetime.utcnow().isoformat(timespec="seconds")
    status = np.where(df["isReso"].to_numpy(), "Reso", "Spedito")
    records = _build_records(df, row_id, key_ordine, key_composito, status, 0, None, fonte_file, now)

    prima = conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0]
    _executemany_chunked(conn, _INSERT_SQL, records, progress=progress)
    dopo = conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0]
    nuove = dopo - prima
    stats = {"righe_nel_file": len(df), "righe_nuove": nuove, "righe_gia_presenti": len(df) - nuove}
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
    Nessuna riga (a nessuno stato) con nessuna delle due chiavi -> INSERT standalone
    (rimborso extra).
    """
    esito = {"convertiti": 0, "duplicati": 0, "standalone": 0}
    if df.empty:
        return esito

    key_ordine_resi = _key_ordine_series(df).to_numpy()
    key_composito_resi = _key_composito_series(df).to_numpy()
    data_reso_fmt = _fmt_date_series(df["dataReso"])  # precomputato una volta, non per-riga in loop
    n = len(df)
    now = datetime.utcnow().isoformat(timespec="seconds")
    log_rows = []

    ordine_id_arr = df["ordineId"].to_numpy()
    sku13_arr = df["sku13"].to_numpy()

    matched_ids: list[str] = []
    matched_modalita: list[str] = []
    matched_data_reso: list[str | None] = []
    remaining_positions: list[int] = []
    standalone_positions: list[int] = []
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
                standalone_positions.append(j)
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

    # --- INSERT righe standalone (rimborso extra) ---
    if standalone_positions:
        st = df.iloc[standalone_positions].reset_index(drop=True)
        st_key_ordine = key_ordine_resi[standalone_positions]
        st_key_comp = key_composito_resi[standalone_positions]
        st_hash = _content_hash_series(st)
        occ = st_hash.groupby(st_hash).cumcount()
        st_id = ("REXTRA-" + st_hash + "#" + occ.astype(str)).to_numpy()

        records = _build_records(st, st_id, st_key_ordine, st_key_comp, ["Reso"] * len(st), 1,
                                  "STANDALONE", fonte_file, now)
        st_ordine_id = st["ordineId"].to_numpy()
        st_sku13 = st["sku13"].to_numpy()
        log_rows.extend(
            (now, fonte_file, "standalone", oid, oid, str(sku), kcomp, "STANDALONE")
            for oid, sku, kcomp in zip(st_ordine_id, st_sku13, st_key_comp)
        )
        _executemany_chunked(conn, _INSERT_SQL, records, progress=progress)
        esito["standalone"] = len(standalone_positions)

    if log_rows:
        conn.executemany(
            "INSERT INTO log_match (ts, fonte_file, esito, ordine_id, ordine_id_resi, sku13, key_comp, modalita) "
            "VALUES (?,?,?,?,?,?,?,?)", log_rows,
        )
    conn.execute(
        "INSERT INTO upload_log (ts, fonte_file, tipo, righe_nel_file, convertiti, duplicati, standalone) "
        "VALUES (?,?,?,?,?,?,?)",
        (now, fonte_file, "RESI", len(df), esito["convertiti"], esito["duplicati"], esito["standalone"]),
    )
    conn.commit()
    return esito


# --------------------------------------------------------------------------------------
# Query per range di date — sostituisce run_pipeline: ritorna DataFrame nella stessa forma
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
        return df
    df["dataVendita"] = pd.to_datetime(df["data_vendita"], errors="coerce")
    df["dataReso"] = pd.to_datetime(df["data_reso"], errors="coerce")
    df["isPromo"] = df["isPromo"].astype(bool)
    for c in ("mkp", "nazione", "clzMappata", "taglia", "genere", "tipoSpedizione"):
        df[c] = df[c].astype("category")
    return df


def _finalize_period_df(df: pd.DataFrame, period_start, period_end) -> pd.DataFrame:
    """Applica la semantica 'reso conta solo se data_reso è nello stesso periodo' (equivalente
    query-time di apply_period_bound_to_returns) e ricostruisce le colonne derivate che
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


def query_period(conn: sqlite3.Connection, start, end, perimetro: str = "1") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ritorna (venduto_df, reso_extra_df) per il periodo [start, end] (date incluse).
    `venduto_df` ha ESATTAMENTE la forma prodotta da engine.process_dataset(): può essere
    passato invariato a metrics.py/report_builders.py. `reso_extra_df` è l'equivalente di
    esito_resi['standalone'] atteso da metrics.compute_channel_kpi."""
    start_s, end_s = _fmt_date(start), _fmt_date(end)
    period_start, period_end = pd.Timestamp(start), pd.Timestamp(end)

    where_perimetro = ""
    if perimetro == "2":
        where_perimetro = " AND tipo_spedizione='DIRETTO'"
    elif perimetro == "3":
        where_perimetro = " AND tipo_spedizione='ESTERNA'"

    q_venduto = (f"SELECT {_SELECT_COLS} FROM righe WHERE is_rimborso_extra=0 "
                 f"AND data_vendita BETWEEN ? AND ?{where_perimetro}")
    rows_v = conn.execute(q_venduto, (start_s, end_s)).fetchall()
    venduto = _rows_to_df(rows_v, _SELECT_COLS.split(", "))
    venduto = _finalize_period_df(venduto, period_start, period_end)

    q_reso_extra = (f"SELECT {_SELECT_COLS} FROM righe WHERE status='Reso' AND data_reso BETWEEN ? AND ? "
                     f"AND (data_vendita IS NULL OR data_vendita < ? OR data_vendita > ?){where_perimetro}")
    rows_r = conn.execute(q_reso_extra, (start_s, end_s, start_s, end_s)).fetchall()
    reso_extra = _rows_to_df(rows_r, _SELECT_COLS.split(", "))
    if not reso_extra.empty:
        # per il reso extra tutto l'importo diventa "reso" a prescindere dal range: è
        # interamente un decremento del fatturato reale del periodo (stessa semantica di
        # esito.standalone nel motore a file).
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
    row = conn.execute("SELECT MIN(data_vendita), MAX(data_vendita) FROM righe WHERE is_rimborso_extra=0").fetchone()
    return row[0], row[1]


def get_upload_log(conn: sqlite3.Connection, limit: int = 200) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT ts, fonte_file, tipo, righe_nel_file, righe_nuove, righe_gia_presenti, "
        "convertiti, duplicati, standalone FROM upload_log ORDER BY ts DESC LIMIT ?",
        conn, params=(limit,))


def get_match_log(conn: sqlite3.Connection, fonte_file: str | None = None, esito: str | None = None,
                   limit: int = 1000) -> pd.DataFrame:
    q = "SELECT ts, fonte_file, esito, ordine_id, ordine_id_resi, sku13, key_comp, modalita FROM log_match WHERE 1=1"
    params: list = []
    if fonte_file:
        q += " AND fonte_file = ?"
        params.append(fonte_file)
    if esito:
        q += " AND esito = ?"
        params.append(esito)
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    return pd.read_sql_query(q, conn, params=params)


def get_stats(conn: sqlite3.Connection) -> dict:
    tot = conn.execute("SELECT COUNT(*) FROM righe").fetchone()[0]
    spediti = conn.execute("SELECT COUNT(*) FROM righe WHERE status='Spedito'").fetchone()[0]
    resi = conn.execute("SELECT COUNT(*) FROM righe WHERE status='Reso'").fetchone()[0]
    standalone = conn.execute("SELECT COUNT(*) FROM righe WHERE is_rimborso_extra=1").fetchone()[0]
    start, end = get_data_bounds(conn)
    return {"righe_totali": tot, "spediti": spediti, "resi": resi, "standalone": standalone,
            "data_min": start, "data_max": end}
