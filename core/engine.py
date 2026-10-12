"""
Motore dati centralizzato — porting vettorizzato (pandas) di backend.gs:
loadMasterData() -> load_anagrafica()
processDataset() -> process_dataset()

Differenze rispetto all'originale Apps Script, dovute al cambio di sorgente dati
(Google Sheet -> CSV):
- Le colonne vengono lette per POSIZIONE (0-based), non per nome header, perché
  l'export CSV può avere header con encoding corrotto (es. "Quantità" -> mojibake).
  Il layout deve restare quello di CONFIG.COLS_DATASET su tutti e 4 i file
  (DATASET, DATASET OLD, RESI, RESI OLD).
- Le date, in Google Sheets, arrivano già come oggetti Date; nel CSV arrivano come
  testo "dd/MM/yyyy". La data segnaposto "01/01/0001" (= nessun reso) esce fuori
  range per pandas.Timestamp e diventa naturalmente NaT (equivalente a "data non
  valida" come nell'originale).
- L'IVA: l'originale usa `masterData.iva = CONFIG.IVA` (che contiene SOLO 'IT': 0.21)
  con fallback CONFIG.DEFAULT_IVA = 0.21. Il risultato pratico è che l'aliquota IVA
  usata per il netto è SEMPRE 0.21 indipendentemente dalla nazione (CONFIG.IVA2, con
  le aliquote per paese, non viene mai referenziato in processDataset). Questo porting
  riproduce fedelmente questo comportamento — non lo "corregge" silenziosamente.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from . import config as CFG


# --------------------------------------------------------------------------------------
# Lettura CSV grezzo
# --------------------------------------------------------------------------------------

def _sniff_sep_and_encoding(raw_bytes: bytes) -> tuple[str, str]:
    """Ritorna (separatore ';', encoding indovinato guardando solo l'inizio del file (poche decine di KB),
    non l'intero contenuto: su file da centinaia di migliaia di righe, evitare di fare fino a
    8 parse completi del file (uno per ogni combinazione sep/encoding) è la differenza fra
    qualche secondo e un timeout/crash."""
    if raw_bytes[:3] == b"\xef\xbb\xbf":
        encoding = "utf-8-sig"
    else:
        try:
            raw_bytes[:65536].decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "cp1252"

    return ";", encoding


def read_raw_csv(file_or_path, sep: str | None = None) -> pd.DataFrame:
    """
    Legge un CSV DATASET/RESI (stesso layout per tutti e 4 i tab) come stringhe grezze,
    posizionale (nessun header usato per il mapping colonne). Percorso veloce: individua
    separatore/encoding guardando solo l'header (una riga), poi fa UN SOLO parse completo del
    file — così un file da 450k righe non viene riletto più volte. Se il parse veloce fallisce
    (formato inatteso), ripiega sul tentativo esaustivo (tutte le combinazioni), più lento ma
    più tollerante.
    """
    raw_bytes = _to_bytes(file_or_path)

    guessed_sep, guessed_enc = _sniff_sep_and_encoding(raw_bytes)
    try:
        df = pd.read_csv(
            io.BytesIO(raw_bytes), sep=sep or guessed_sep, header=None, skiprows=1, dtype=str,
            quotechar='"', engine="c", encoding=guessed_enc, on_bad_lines="skip", keep_default_na=False,
        )
        if df.shape[1] > 1:
            return df
    except (UnicodeDecodeError, pd.errors.ParserError, MemoryError):
        pass

    seps_to_try = [sep] if sep else [";"]
    last_err = None
    for candidate_sep in seps_to_try:
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            if candidate_sep == guessed_sep and enc == guessed_enc:
                continue  # già provato sopra
            try:
                df = pd.read_csv(
                    io.BytesIO(raw_bytes),
                    sep=candidate_sep,
                    header=None,
                    skiprows=1,
                    dtype=str,
                    quotechar='"',
                    engine="c",
                    encoding=enc,
                    on_bad_lines="skip",
                    keep_default_na=False,
                )
                if df.shape[1] > 1:
                    return df
            except (UnicodeDecodeError, pd.errors.ParserError) as e:
                last_err = e
                continue
    if last_err:
        raise last_err
    raise ValueError("Il file non è un CSV con separatore ';' (meno di due colonne).")


def _to_bytes(file_or_path) -> bytes:
    if hasattr(file_or_path, "read"):
        data = file_or_path.read()
        if isinstance(data, str):
            return data.encode("utf-8")
        return data
    with open(file_or_path, "rb") as f:
        return f.read()


# Colonne ANAGRAFICA legacy (0-based): sku=0, clz=4, serie=5, cod=6, desc=9, genere=13.
ANAG_COLS = {"SKU": 0, "CLZ": 4, "SERIE": 5, "COD": 6, "DESC": 9, "GENERE": 13}


def deduce_genere(brand: str, linea: str, col6: str = "", cat: str = "", desc: str = "") -> str:
    """Classifica il genere (macro-categoria) da brand, linea/serie, codice reparto, categoria e descrizione.
    Ritorna uno dei generi principali ('BAMBINO', 'DONNA', 'UOMO', 'UNISEX', 'ACCESSORI', 'ABBIGLIAMENTO')
    oppure 'NON CLASSIFICATO'.
    """
    b = (brand or "").upper().strip()
    l = (linea or "").upper().strip()
    c = (cat or "").upper().strip()
    d = (desc or "").upper().strip()

    if "ABBIGL" in b or "ABBIGL" in l or "ABBIGL" in d:
        return "ABBIGLIAMENTO"
    if "ACCESSORI" in b or "ACCESSORI" in l or "ACCESSORI" in d or c == "PUB" or "MARKETING" in l or "PUBBLICIT" in b or "PUBBLICIT" in l:
        return "ACCESSORI"

    # Ricerca bambini / kids / newborn
    if any(k in b or k in l or k in d for k in (
        "BIMBO", "BIMBA", "CULLA", "FALCOTTO", "NATURINO", "KID", "KIDS",
        "CHILD", "NEW BORN", "NEONATO", "BABY"
    )):
        return "BAMBINO"
    if l.startswith("F8 "):
        return "BAMBINO"
    if b in ("STUART WEITZMAN", "HOSHIKAI", "GUCCI BIMBO", "W6YZ BIMBO", "GOLDEN GOOSE"):
        return "BAMBINO"

    # Controllo esplicito su descrizione / linea per Donna / Uomo
    if "DONNA" in l or " D " in l or l.endswith(" D") or l.startswith("DONNA ") or " DONNA" in d or "DONNA " in d or d.endswith(" DONNA"):
        return "DONNA"
    if "UOMO" in l or " U " in l or l.endswith(" U") or l.startswith("UOMO ") or " UOMO" in d or "UOMO " in d or d.endswith(" UOMO"):
        return "UOMO"
    if "UNISEX" in l or " UNI " in l or "UNISEX" in d:
        return "UNISEX"

    if "CANDICE COOPER" in b:
        return "DONNA"
    if "FLOWER MOUNTAIN" in b:
        return "UNISEX"
    if "VOILE BLANCHE" in b:
        donna_models = ("ALICE", "KARLIE", "LIVYA", "ILDA", "LEDA", "ELLEN", "DOMITILLA", "VISSIA", "HILLY", "FREIA", "CATERINA")
        if any(m in d for m in donna_models):
            return "DONNA"
        if "BULL" in d:
            return "UOMO"
        return "DONNA"
    return "NON CLASSIFICATO"


def parse_anagrafica(file_or_path, fonte_file: str = "anagrafica.csv") -> list[dict]:
    """Effettua il parsing di un file anagrafica (supporta formati TSV \t moderni come anagrafica_261.csv / anagrafica_262.csv
    con tolleranza alle virgolette non chiuse ed encoding vari, e formati CSV legacy con ';').
    Ritorna una lista di dizionari pronti per essere inseriti o aggiornati nel DB (db.upsert_anagrafica).
    """
    raw_bytes = _to_bytes(file_or_path)
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw_bytes.decode("utf-8", errors="replace")

    lines = text.splitlines()
    records: list[dict] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

    first_non_empty = next((line for line in lines if line.strip()), "")
    sep = "\t" if "\t" in first_non_empty else ";"

    reader = csv.reader(lines, delimiter=sep, quoting=csv.QUOTE_NONE)
    for row in reader:
        if not row or all(c.strip() == "" for c in row):
            continue
        cleaned = [c.strip().strip("\"") for c in row]
        if len(cleaned) < 10:
            continue

        # Salta eventuale riga di intestazione
        if cleaned[0].lower() in ("anno", "stagione", "sku", "season"):
            continue

        # Formato standard TSV a 19 colonne (es. anagrafica_261 / 262)
        if len(cleaned) >= 14 and sep == "\t":
            def g(idx, default=""):
                return cleaned[idx] if idx < len(cleaned) else default

            sku7 = g(9)
            fondo_cod = g(11)
            colore_cod = g(13)
            if not sku7:
                continue

            sku13 = (sku7 + fondo_cod + colore_cod).replace("-", "").strip()
            brand = g(3)
            linea = g(5)
            cat = g(8)
            col6 = g(6)
            desc = g(10)
            genere = deduce_genere(brand, linea, col6, cat, desc)

            records.append({
                "sku13": sku13,
                "sku7": sku7,
                "brand_cod": g(2),
                "brand": brand,
                "linea_cod": g(4),
                "linea": linea,
                "reparto_cod": col6,
                "tipo_cod": g(7),
                "categoria": cat,
                "descrizione": g(10),
                "fondo_cod": fondo_cod,
                "fondo_desc": g(12),
                "colore_cod": colore_cod,
                "colore_desc": g(14),
                "taglia_base": g(15),
                "valore": g(16),
                "data_disponibilita": g(17),
                "flag": g(18),
                "stagione": g(0),
                "semestre": g(1),
                "genere": genere,
                "fonte_file": fonte_file,
                "aggiornato_il": now,
            })
        elif len(cleaned) >= 14:
            # Layout legacy con ';' (ANAG_COLS)
            c = ANAG_COLS
            n = len(cleaned)
            sku = cleaned[c["SKU"]] if c["SKU"] < n else ""
            if not sku:
                continue
            sku_clean = sku.replace("-", "").strip()
            sku7 = sku_clean[:7]
            sku13 = sku_clean[:13]
            desc = cleaned[c["DESC"]] if c["DESC"] < n else ""
            clz = cleaned[c["CLZ"]] if c["CLZ"] < n else ""
            serie = cleaned[c["SERIE"]] if c["SERIE"] < n else ""
            genere = cleaned[c["GENERE"]] if c["GENERE"] < n else ""
            records.append({
                "sku13": sku13,
                "sku7": sku7,
                "brand_cod": "",
                "brand": clz,
                "linea_cod": "",
                "linea": serie,
                "reparto_cod": "",
                "tipo_cod": "",
                "categoria": "",
                "descrizione": desc,
                "fondo_cod": "",
                "fondo_desc": "",
                "colore_cod": "",
                "colore_desc": "",
                "taglia_base": "",
                "valore": "",
                "data_disponibilita": "",
                "flag": "",
                "stagione": "",
                "semestre": "",
                "genere": genere or deduce_genere(clz, serie, "", "", desc),
                "fonte_file": fonte_file,
                "aggiornato_il": now,
            })

    return records


def load_anagrafica(file_or_path=None) -> dict:
    """Ritorna { sku_or_cod: {desc, modello, clz, serie, genere, ...} }.
    Se `file_or_path` è None, tenta di recuperare l'anagrafica salvata nel DB SQLite.
    Se il file è fornito, ne esegue il parsing e costruisce la mappa in memoria.
    """
    if file_or_path is None:
        try:
            from . import db
            conn = db.connect()
            d = db.get_anagrafica_dict(conn)
            if d:
                return d
        except Exception:
            pass
        return {}

    records = parse_anagrafica(file_or_path)
    if not records:
        return {}

    anag: dict[str, dict] = {}
    for r in records:
        sku13 = r["sku13"]
        sku7 = r["sku7"]
        desc_val = r["descrizione"] or "-"
        stag_val = f"{r['stagione']}/{r['semestre']}" if r.get("semestre") else (r.get("stagione") or "")
        entry = {
            "desc": desc_val,
            "modello": desc_val,
            "clz": r["brand"] or "-",
            "serie": r["linea"] or "-",
            "genere": r["genere"] or "NON CLASSIFICATO",
            "materiale": r["fondo_desc"] or "",
            "colore": r["colore_desc"] or "",
            "taglia_base": r["taglia_base"] or "",
            "stagione": stag_val,
            "cod": sku7 or "",
            "sku": sku13 or "",
        }
        if sku13:
            anag[sku13] = entry
        if sku7 and (sku7 not in anag or (anag[sku7].get("genere") == "NON CLASSIFICATO" and entry["genere"] != "NON CLASSIFICATO")):
            anag[sku7] = entry

    return anag


# --------------------------------------------------------------------------------------
# process_dataset — porting vettorizzato di processDataset()
# --------------------------------------------------------------------------------------

_TAGLIA_NUMERIC_RE = re.compile(r"^\d+/?$")
_TAGLIA_LETTER_RE = re.compile(r"^(XXS|XS|S|M|L|XL|XXL|XXXL)$", re.IGNORECASE)

_GENERI_PRINCIPALI = {"BAMBINO", "BAMBINA", "UOMO", "DONNA", "UNISEX", "ACCESSORI", "ABBIGLIAMENTO"}


def process_dataset(df_raw: pd.DataFrame, anagrafica: dict | None = None) -> pd.DataFrame:
    """
    Ritorna un DataFrame "processedRows" equivalente a quello prodotto da processDataset()
    in backend.gs, con le stesse colonne calcolate (nomi in italiano/camelCase originali,
    tradotti in snake_case Python).
    Se anagrafica non è fornita (None), tenta di recuperarla dal DB SQLite.
    """
    if anagrafica is None:
        anagrafica = load_anagrafica(None)
    c = CFG.COLS_DATASET
    n = df_raw.shape[1]
    if n < CFG.N_COLS:
        # padding difensivo se il CSV ha meno colonne del previsto
        for extra in range(n, CFG.N_COLS):
            df_raw[extra] = ""

    df = pd.DataFrame(index=df_raw.index)

    def col(idx):
        return df_raw[idx].astype(str).str.strip()

    mkp_raw = col(c["MKP"])
    valuta_raw = col(c["VALUTA"]).str.upper()
    sku_raw = col(c["SKU_FULL"])

    mask_valid = (valuta_raw != "") & (mkp_raw != "") & (sku_raw != "")

    naz_raw = col(c["NAZ"])
    clz_raw = col(c["CLZ"])
    stato_raw = col(c["STATO"]).str.lower()
    acquirente_raw = col(c["ACQUIRENTE"]).str.upper()

    is_reso = stato_raw == "reso"
    nazione = naz_raw.str.lower().map(CFG.MAP_NATION).fillna(naz_raw.str.upper())
    clz_mappata = clz_raw.map(CFG.MAP_COLLECTION)
    clz_mappata = clz_mappata.fillna(clz_raw.where(clz_raw != "", "NON MAPPATE"))
    clz_mappata = clz_mappata.mask(clz_mappata == "", "NON MAPPATE")

    # --- SKU / taglia ---
    sku_pulita = sku_raw.str.replace("-", "", regex=False)
    sku13 = sku_pulita.str.slice(0, 13)
    sku7 = sku_pulita.str.slice(0, 7)
    taglia_raw = sku_raw.str.split("-").str[-1].fillna("").str.strip()

    taglia = np.select(
        [
            taglia_raw == "",
            taglia_raw.str.match(_TAGLIA_NUMERIC_RE),
            taglia_raw.str.match(_TAGLIA_LETTER_RE),
        ],
        [
            "UNICA",
            taglia_raw,
            taglia_raw.str.upper(),
        ],
        default="ND",
    )
    taglia = pd.Series(taglia, index=df.index)

    # --- genere (da anagrafica, opzionale) ---
    genere_by_sku13 = sku13.map(lambda s: anagrafica.get(s, {}).get("genere", ""))
    genere_by_sku7 = sku7.map(lambda s: anagrafica.get(s, {}).get("genere", ""))
    genere_raw = genere_by_sku13.where(genere_by_sku13 != "", genere_by_sku7)

    def _macro_genere(g):
        g = (g or "").strip()
        if g == "":
            return "NON CLASSIFICATO"
        gu = g.upper()
        return gu if gu in _GENERI_PRINCIPALI else "NON MAPPATO"

    macro_genere = genere_raw.map(_macro_genere)

    # --- importi ---
    def parse_number(series: pd.Series) -> pd.Series:
        s = series.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        return pd.to_numeric(s, errors="coerce").fillna(0.0)

    importo_originale = parse_number(col(c["IMPORTO"]))
    qta = pd.to_numeric(col(c["QTA"]), errors="coerce").fillna(0.0)

    rate = valuta_raw.map(CFG.TASSI_CAMBIO).fillna(1.00)
    lordo_eur = importo_originale / rate
    iva_rate = nazione.map(CFG.IVA).fillna(CFG.DEFAULT_IVA)
    netto_eur = lordo_eur / (1 + iva_rate)

    qta_abs = qta.abs()
    lordo_abs = lordo_eur.abs()
    netto_abs = netto_eur.abs()

    promo_num = pd.to_numeric(col(c["PROMO"]), errors="coerce")
    is_promo = promo_num == 1

    paia_spedite = qta_abs
    paia_rese = paia_spedite.where(is_reso, 0.0)
    paia_nette = paia_spedite - paia_rese

    lordo_spedito = lordo_abs
    lordo_reso = lordo_spedito.where(is_reso, 0.0)
    lordo_netto = lordo_spedito - lordo_reso

    netto_spedito = netto_abs
    netto_reso = netto_spedito.where(is_reso, 0.0)
    netto_netto = netto_spedito - netto_reso

    ordine_id = col(c["ORDINE_ID"]).str.upper()
    riga_ordine = col(c["RIGA_ID"])

    tipo_spedizione = np.where(
        ordine_id.str.contains("|".join(re.escape(s) for s in CFG.LOGISTICA_ESTERNA), regex=True, na=False),
        "ESTERNA", "DIRETTO",
    )

    data_vendita = pd.to_datetime(col(c["DATA"]), format="%d/%m/%Y", errors="coerce")
    data_reso = pd.to_datetime(col(c["DATA_RESO"]), format="%d/%m/%Y", errors="coerce")
    # Placeholder "nessuna data" (es. "01/01/0001"): con pandas >= 2 la risoluzione 'us' del
    # datetime64 riesce a rappresentare anche l'anno 1, quindi NON diventa NaT da sola come
    # accadeva con la risoluzione 'ns' classica. Lo normalizziamo qui esplicitamente.
    data_vendita = data_vendita.where(data_vendita.dt.year > 1900)
    data_reso = data_reso.where(data_reso.dt.year > 1900)

    out = pd.DataFrame({
        "mkp": mkp_raw, "nazione": nazione, "clzOriginale": clz_raw, "clzMappata": clz_mappata,
        "skuFull": sku_raw, "sku13": sku13, "sku7": sku7, "taglia": taglia, "genere": macro_genere,
        "acquirente": acquirente_raw,
        "qta": paia_nette, "lordoEUR": lordo_netto, "nettoEUR": netto_netto,
        "paiaSpedite": paia_spedite, "paiaRese": paia_rese, "paiaNette": paia_nette,
        "nettoSpedito": netto_spedito, "nettoReso": netto_reso, "nettoNetto": netto_netto,
        "lordoSpedito": lordo_spedito, "lordoReso": lordo_reso, "lordoNetto": lordo_netto,
        "dataVendita": data_vendita, "dataReso": data_reso,
        "isReso": is_reso, "ordineId": ordine_id, "rigaOrdine": riga_ordine,
        "tipoSpedizione": tipo_spedizione, "isPromo": is_promo,
    })

    out = out[mask_valid].reset_index(drop=True)
    out["matchedVia"] = ""

    # Dtype 'category' sulle colonne a bassa cardinalità: su dataset grandi (100k+ righe)
    # taglia/nazione/genere/tipoSpedizione/clzMappata si ripetono moltissimo, e la category
    # riduce l'uso di RAM di un ordine di grandezza rispetto a stringhe Python ripetute.
    for col in ("mkp", "nazione", "clzMappata", "taglia", "genere", "tipoSpedizione"):
        out[col] = out[col].astype("category")

    return out
