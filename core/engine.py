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

import io
import re
import numpy as np
import pandas as pd

from . import config as CFG


# --------------------------------------------------------------------------------------
# Lettura CSV grezzo
# --------------------------------------------------------------------------------------

def read_raw_csv(file_or_path) -> pd.DataFrame:
    """
    Legge un CSV DATASET/RESI (stesso layout per tutti e 4 i tab) come stringhe grezze,
    posizionale (nessun header usato per il mapping colonne). Gestisce ; come separatore,
    campi quotati, e tenta più encoding (i file esportati da alcuni gestionali non sono
    sempre UTF-8 pulito).
    """
    raw_bytes = _to_bytes(file_or_path)
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(
                io.BytesIO(raw_bytes),
                sep=";",
                header=None,
                skiprows=1,
                dtype=str,
                quotechar='"',
                engine="c",
                encoding=enc,
                on_bad_lines="skip",
                keep_default_na=False,
            )
            return df
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            last_err = e
            continue
    raise last_err


def _to_bytes(file_or_path) -> bytes:
    if hasattr(file_or_path, "read"):
        data = file_or_path.read()
        if isinstance(data, str):
            return data.encode("utf-8")
        return data
    with open(file_or_path, "rb") as f:
        return f.read()


# --------------------------------------------------------------------------------------
# ANAGRAFICA (facoltativa) — porting di loadMasterData()
# --------------------------------------------------------------------------------------

# Colonne ANAGRAFICA (0-based), come in loadMasterData: sku=0, clz=4, serie=5, cod=6,
# desc=9, genere=13.
ANAG_COLS = {"SKU": 0, "CLZ": 4, "SERIE": 5, "COD": 6, "DESC": 9, "GENERE": 13}


def load_anagrafica(file_or_path=None) -> dict:
    """
    Ritorna { sku_or_cod: {desc, clz, serie, genere} }. Se `file_or_path` è None,
    ritorna un dizionario vuoto (i report continuano a funzionare, ma senza descrizioni
    articolo e senza classificazione per genere: 'NON CLASSIFICATO' ovunque, come faceva
    l'originale quando la tab ANAGRAFICA era assente/vuota).
    """
    if file_or_path is None:
        return {}

    raw_bytes = _to_bytes(file_or_path)
    df = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(
                io.BytesIO(raw_bytes), sep=";", header=None, skiprows=1, dtype=str,
                quotechar='"', engine="c", encoding=enc, on_bad_lines="skip",
                keep_default_na=False,
            )
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    if df is None or df.empty:
        return {}

    n = df.shape[1]
    anag: dict[str, dict] = {}
    c = ANAG_COLS
    for row in df.itertuples(index=False, name=None):
        sku = str(row[c["SKU"]]).strip() if c["SKU"] < n else ""
        if not sku:
            continue
        entry = {
            "desc": str(row[c["DESC"]]).strip() if c["DESC"] < n else "",
            "clz": str(row[c["CLZ"]]).strip() if c["CLZ"] < n else "",
            "serie": str(row[c["SERIE"]]).strip() if c["SERIE"] < n else "",
            "genere": str(row[c["GENERE"]]).strip() if c["GENERE"] < n else "",
        }
        anag[sku] = entry
        cod = str(row[c["COD"]]).strip() if c["COD"] < n else ""
        if cod and cod not in anag:
            anag[cod] = entry
    return anag


# --------------------------------------------------------------------------------------
# process_dataset — porting vettorizzato di processDataset()
# --------------------------------------------------------------------------------------

_TAGLIA_NUMERIC_RE = re.compile(r"^\d+/?$")
_TAGLIA_LETTER_RE = re.compile(r"^(XXS|XS|S|M|L|XL|XXL|XXXL)$", re.IGNORECASE)

_GENERI_PRINCIPALI = {"BAMBINO", "BAMBINA", "UOMO", "DONNA", "UNISEX", "ACCESSORI", "ABBIGLIAMENTO"}


def process_dataset(df_raw: pd.DataFrame, anagrafica: dict) -> pd.DataFrame:
    """
    Ritorna un DataFrame "processedRows" equivalente a quello prodotto da processDataset()
    in backend.gs, con le stesse colonne calcolate (nomi in italiano/camelCase originali,
    tradotti in snake_case Python).
    """
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
    return out
