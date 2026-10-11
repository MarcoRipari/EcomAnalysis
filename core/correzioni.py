"""
Correzioni del DB: "trova e sostituisci" su una colonna, con condizioni.

Esempio: colonna Nazione, cerca "UNITED KIN" (uguale a), sostituisci con "GB".

- `anteprima` mostra cosa cambierebbe (valore attuale → nuovo valore, numero di righe, campione)
  SENZA modificare nulla; `applica` esegue la stessa identica sostituzione.
- Si possono modificare solo colonne descrittive che NON entrano nell'id della riga (hash di
  ordine, riga, sku, taglia, data, acquirente, importo, paia): così ricaricare un file già
  caricato resta idempotente e le correzioni non si perdono. Cambiando Marketplace o Nazione
  la chiave composita usata dalla riconciliazione dei resi viene ricalcolata.
- Una correzione può essere salvata come *regola*: viene riapplicata automaticamente a ogni
  nuovo DATASET/RESI caricato (db.upsert_dataset / db.upsert_resi), così il dato errato non
  rientra dai file successivi.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

# colonna DB → etichetta (colonne che si possono MODIFICARE)
COLONNE_MODIFICABILI = {
    "nazione": "Nazione",
    "mkp": "Marketplace",
    "clz_originale": "Collezione originale",
    "clz_mappata": "Brand (collezione mappata)",
    "genere": "Genere",
    "tipo_spedizione": "Tipo spedizione (DIRETTO / ESTERNA)",
}
# colonne utilizzabili nelle CONDIZIONI (le prime sono valutabili anche sui file in caricamento)
COLONNE_CONDIZIONE_FILE = {
    **COLONNE_MODIFICABILI,
    "acquirente": "Acquirente", "taglia": "Taglia", "sku13": "SKU (13 caratteri)",
    "sku7": "Codice articolo (7 caratteri)", "ordine_id": "Ordine",
}
COLONNE_CONDIZIONE = {**COLONNE_CONDIZIONE_FILE, "status": "Stato riga (Spedito/Reso)",
                      "fonte_file": "File di origine"}

# colonna DB → colonna del DataFrame prodotto da engine.process_dataset
_COL_DF = {"nazione": "nazione", "mkp": "mkp", "clz_originale": "clzOriginale", "clz_mappata": "clzMappata",
           "genere": "genere", "tipo_spedizione": "tipoSpedizione", "acquirente": "acquirente",
           "taglia": "taglia", "sku13": "sku13", "sku7": "sku7", "ordine_id": "ordineId"}

OPERATORI = ["uguale a", "diverso da", "contiene", "non contiene", "inizia con", "finisce con",
             "è vuoto", "non è vuoto"]
_SENZA_VALORE = {"è vuoto", "non è vuoto"}
MODI = {"intero": "Sostituisci l'intero valore", "testo": "Sostituisci solo il testo trovato"}


@dataclass
class Regola:
    colonna: str
    operatore: str
    cerca: str
    sostituisci: str
    modo: str = "intero"                  # "intero" | "testo"
    ignora_maiuscole: bool = True
    condizioni: list[dict] = field(default_factory=list)   # [{"colonna", "operatore", "valore"}]
    data_da: str | None = None            # filtro su Data Pagamento (YYYY-MM-DD), estremi inclusi
    data_a: str | None = None

    def valida(self) -> None:
        if self.colonna not in COLONNE_MODIFICABILI:
            raise ValueError(f"Colonna non modificabile: {self.colonna}")
        if self.operatore not in OPERATORI:
            raise ValueError(f"Operatore non valido: {self.operatore}")
        if self.operatore not in _SENZA_VALORE and self.cerca == "":
            raise ValueError("Indica cosa cercare (oppure usa «è vuoto»).")
        if self.modo not in MODI:
            raise ValueError(f"Modo non valido: {self.modo}")
        if self.modo == "testo" and (self.operatore in _SENZA_VALORE or self.operatore in ("diverso da", "non contiene")):
            raise ValueError("«Sostituisci solo il testo trovato» richiede un operatore che trova del testo.")
        for c in self.condizioni:
            if c.get("colonna") not in COLONNE_CONDIZIONE:
                raise ValueError(f"Colonna non valida nelle condizioni: {c.get('colonna')}")
            if c.get("operatore") not in OPERATORI:
                raise ValueError(f"Operatore non valido nelle condizioni: {c.get('operatore')}")

    @property
    def salvabile(self) -> bool:
        """Le regole permanenti si valutano sui file in caricamento: niente colonne solo-DB."""
        return all(c.get("colonna") in COLONNE_CONDIZIONE_FILE for c in self.condizioni)


# ---------------------------------------------------------------------------------------
# Logica di confronto, in due versioni equivalenti (SQL sul DB, pandas sui file in caricamento)
# ---------------------------------------------------------------------------------------
def _clausola_sql(colonna: str, operatore: str, valore: str, ci: bool) -> tuple[str, list]:
    """`colonna` viene SEMPRE dalle whitelist di questo modulo (mai da input libero)."""
    vuoto = f"({colonna} IS NULL OR TRIM({colonna}) = '')"
    if operatore == "è vuoto":
        return vuoto, []
    if operatore == "non è vuoto":
        return f"NOT {vuoto}", []
    n = len(valore)
    collate = " COLLATE NOCASE" if ci else ""
    if operatore == "uguale a":
        return f"{colonna}{collate} = ?", [valore]
    if operatore == "diverso da":
        return f"({colonna} IS NULL OR {colonna}{collate} != ?)", [valore]
    if operatore in ("contiene", "non contiene"):
        trovato = "instr(lower({c}), lower(?)) > 0" if ci else "instr({c}, ?) > 0"
        trovato = trovato.format(c=colonna)
        return (trovato if operatore == "contiene" else f"NOT COALESCE({trovato}, 0)"), [valore]
    if operatore == "inizia con":
        return f"substr({colonna}, 1, {n}){collate} = ?", [valore]
    if operatore == "finisce con":
        return f"substr({colonna}, -{n}){collate} = ?", [valore]
    raise ValueError(operatore)


def _mask_df(serie: pd.Series, operatore: str, valore: str, ci: bool) -> pd.Series:
    s = serie.astype(str).str.strip() if operatore in _SENZA_VALORE else serie.astype(str)
    if operatore == "è vuoto":
        return s == ""
    if operatore == "non è vuoto":
        return s != ""
    a, b = (s.str.lower(), valore.lower()) if ci else (s, valore)
    if operatore == "uguale a":
        return a == b
    if operatore == "diverso da":
        return a != b
    if operatore == "contiene":
        return a.str.contains(b, regex=False)
    if operatore == "non contiene":
        return ~a.str.contains(b, regex=False)
    if operatore == "inizia con":
        return a.str.startswith(b)
    if operatore == "finisce con":
        return a.str.endswith(b)
    raise ValueError(operatore)


def nuovo_valore(vecchio: str | None, r: Regola) -> str:
    """Valore dopo la sostituzione (stessa funzione per DB e file in caricamento)."""
    vecchio = "" if vecchio is None else str(vecchio)
    if r.modo == "testo" and r.operatore not in _SENZA_VALORE:
        return re.sub(re.escape(r.cerca), lambda _m: r.sostituisci, vecchio,
                      flags=re.IGNORECASE if r.ignora_maiuscole else 0)
    return r.sostituisci


def _where_sql(r: Regola) -> tuple[str, list]:
    parti, params = [], []
    sql, p = _clausola_sql(r.colonna, r.operatore, r.cerca, r.ignora_maiuscole)
    parti.append(sql), params.extend(p)
    for c in r.condizioni:
        sql, p = _clausola_sql(c["colonna"], c["operatore"], str(c.get("valore", "")), r.ignora_maiuscole)
        parti.append(sql), params.extend(p)
    if r.data_da:
        parti.append("data_vendita >= ?"), params.append(r.data_da)
    if r.data_a:
        parti.append("data_vendita <= ?"), params.append(r.data_a)
    return " AND ".join(parti), params


# ---------------------------------------------------------------------------------------
# Anteprima e applicazione sul DB
# ---------------------------------------------------------------------------------------
def anteprima(conn: sqlite3.Connection, r: Regola, campione: int = 20) -> dict:
    """{'totale': righe interessate, 'mappa': DataFrame(Valore attuale, Nuovo valore, Righe),
    'campione': DataFrame di righe d'esempio}. Non modifica nulla."""
    r.valida()
    where, params = _where_sql(r)
    cur = conn.execute(f"SELECT {r.colonna}, COUNT(*) FROM righe WHERE {where} GROUP BY {r.colonna} "
                       f"ORDER BY COUNT(*) DESC", params)
    righe = [(v, n, nuovo_valore(v, r)) for v, n in cur.fetchall()]
    righe = [(("" if v is None else v), nuovo, n) for v, n, nuovo in righe if ("" if v is None else v) != nuovo]
    mappa = pd.DataFrame(righe, columns=["Valore attuale", "Nuovo valore", "Righe"])
    esempi = pd.read_sql_query(
        f"SELECT ordine_id AS Ordine, data_vendita AS 'Data vendita', mkp AS Marketplace, nazione AS Nazione, "
        f"clz_mappata AS Brand, sku_full AS SKU, status AS Stato FROM righe WHERE {where} LIMIT {int(campione)}",
        conn, params=params)
    return {"totale": int(mappa["Righe"].sum()) if not mappa.empty else 0, "mappa": mappa, "campione": esempi}


def applica(conn: sqlite3.Connection, r: Regola) -> int:
    """Esegue la sostituzione. Ritorna il numero di righe modificate."""
    r.valida()
    where, params = _where_sql(r)
    try:
        conn.execute("DROP TABLE IF EXISTS temp._corr")
        conn.execute("CREATE TEMP TABLE _corr (rid INTEGER PRIMARY KEY)")
        conn.execute(f"INSERT INTO _corr SELECT rowid FROM righe WHERE {where}", params)
        valori = [v for (v,) in conn.execute(f"SELECT DISTINCT {r.colonna} FROM righe WHERE rowid IN (SELECT rid FROM _corr)")]
        modificate = 0
        for v in valori:
            nuovo = nuovo_valore(v, r)
            if nuovo == ("" if v is None else v):
                continue
            cur = conn.execute(f"UPDATE righe SET {r.colonna} = ? WHERE rowid IN (SELECT rid FROM _corr) "
                               f"AND {r.colonna} IS ?", (nuovo, v))
            modificate += cur.rowcount
        if r.colonna in ("mkp", "nazione") and modificate:
            # la chiave composita (riconciliazione dei resi) contiene marketplace e nazione;
            # stessa formula di db._key_composito_series
            conn.execute(
                "UPDATE righe SET key_composito = mkp || '|' || nazione || '|' || acquirente || '|' || sku13 || '|' "
                "|| taglia || '|' || CAST(ROUND(lordo_spedito * 100) AS INTEGER) "
                "WHERE rowid IN (SELECT rid FROM _corr)")
        conn.execute(
            "INSERT INTO log_correzioni (ts, colonna, operatore, cerca, sostituisci, modo, condizioni, righe) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), r.colonna, r.operatore,
             r.cerca, r.sostituisci, r.modo,
             json.dumps({"condizioni": r.condizioni, "data_da": r.data_da, "data_a": r.data_a}, ensure_ascii=False),
             modificate))
        conn.commit()
        return modificate
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("DROP TABLE IF EXISTS temp._corr")


# ---------------------------------------------------------------------------------------
# Regole permanenti (applicate ai nuovi caricamenti)
# ---------------------------------------------------------------------------------------
def salva_regola(conn: sqlite3.Connection, r: Regola) -> int:
    r.valida()
    if not r.salvabile:
        raise ValueError("Le condizioni su «Stato riga» e «File di origine» non si possono salvare come regola.")
    cur = conn.execute(
        "INSERT INTO regole_correzione (creata_il, colonna, operatore, cerca, sostituisci, modo, ignora_maiuscole, "
        "condizioni, data_da, data_a, attiva) VALUES (?,?,?,?,?,?,?,?,?,?,1)",
        (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), r.colonna, r.operatore,
         r.cerca, r.sostituisci, r.modo, int(r.ignora_maiuscole), json.dumps(r.condizioni, ensure_ascii=False),
         r.data_da, r.data_a))
    conn.commit()
    return int(cur.lastrowid)


def _regola_da_riga(row) -> Regola:
    return Regola(colonna=row[1], operatore=row[2], cerca=row[3], sostituisci=row[4], modo=row[5],
                  ignora_maiuscole=bool(row[6]), condizioni=json.loads(row[7] or "[]"),
                  data_da=row[8], data_a=row[9])


_SELECT_REGOLE = ("SELECT id, colonna, operatore, cerca, sostituisci, modo, ignora_maiuscole, condizioni, "
                  "data_da, data_a, creata_il FROM regole_correzione WHERE attiva=1 ORDER BY id")


def regole_attive(conn: sqlite3.Connection) -> list[Regola]:
    return [_regola_da_riga(row) for row in conn.execute(_SELECT_REGOLE).fetchall()]


def elenco_regole(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id AS ID, colonna AS Colonna, operatore AS Operatore, cerca AS Cerca, sostituisci AS Sostituisci, "
        "modo AS Modo, condizioni AS Condizioni, creata_il AS 'Creata il' FROM regole_correzione "
        "WHERE attiva=1 ORDER BY id", conn)


def elimina_regola(conn: sqlite3.Connection, regola_id: int) -> None:
    conn.execute("UPDATE regole_correzione SET attiva=0 WHERE id=?", (int(regola_id),))
    conn.commit()


def elenco_log(conn: sqlite3.Connection, limite: int = 200) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT ts AS Data, colonna AS Colonna, operatore AS Operatore, cerca AS Cerca, sostituisci AS Sostituisci, "
        "modo AS Modo, righe AS Righe FROM log_correzioni ORDER BY ts DESC LIMIT ?", conn, params=(limite,))


def applica_regole_df(conn: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    """Applica le regole salvate a un DataFrame appena letto da un file (output di process_dataset)."""
    regole = regole_attive(conn)
    if not regole or df.empty:
        return df
    df = df.copy()
    for r in regole:
        col = _COL_DF[r.colonna]
        valori = df[col].astype(str)
        mask = _mask_df(valori, r.operatore, r.cerca, r.ignora_maiuscole)
        for c in r.condizioni:
            mask &= _mask_df(df[_COL_DF[c["colonna"]]].astype(str), c["operatore"], str(c.get("valore", "")),
                             r.ignora_maiuscole)
        if r.data_da:
            mask &= df["dataVendita"] >= pd.Timestamp(r.data_da)
        if r.data_a:
            mask &= df["dataVendita"] <= pd.Timestamp(r.data_a)
        if not mask.any():
            continue
        nuovi = valori[mask].map(lambda v, r=r: nuovo_valore(v, r))
        valori = valori.copy()
        valori[mask] = nuovi
        df[col] = valori.astype("category") if str(df[col].dtype) == "category" else valori
    return df
