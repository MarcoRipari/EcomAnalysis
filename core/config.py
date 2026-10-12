# =========================================================================================
# CONFIGURAZIONI GLOBALI E MAPPE — porting 1:1 da backend.gs (CONFIG)
# =========================================================================================

# Indici colonna (0-based) nei CSV DATASET/DATASET OLD/RESI/RESI OLD.
# Il layout è posizionale (identico in tutti e 4 i file), quindi NON ci basiamo sugli header
# del CSV (che nell'export possono avere encoding corrotto) ma sulla posizione della colonna.
COLS_DATASET = {
    "MKP": 0,
    "NAZ": 1,
    "CLZ": 2,
    "PROMO": 3,
    "DATA": 4,
    "DATA_RESO": 5,
    "STATO": 6,
    "ACQUIRENTE": 7,
    "ORDINE_ID": 8,
    "RIGA_ID": 9,
    "VALUTA": 10,
    "PREZZO": 11,
    "IMPORTO": 12,
    "QTA": 13,
    "COUPON": 14,
    "SKU_FULL": 15,
}

N_COLS = 16

LOGISTICA_ESTERNA = ["_ZFS", "_FBA", "-AMZ"]

DEFAULT_IVA = 0.21

MAP_COLLECTION = {
    "NATURINO COCOON": "NATURINO", "NATURINO CLASSIC": "NATURINO", "NATURINO SNEAKERS": "NATURINO",
    "NATURINO OUTDOOR": "NATURINO", "NATURINO WILD LIFE": "NATURINO", "NATURINO ACTIVE": "NATURINO",
    "NATURINO BABY": "NATURINO", "NATURINO EASY": "NATURINO", "NATURINO BAREFOOT": "NATURINO",
    "NATURINO RELAX": "NATURINO", "NATURINO RAINSTEP": "NATURINO",
    "FALCOTTO SNEAKERS": "FALCOTTO", "FALCOTTO CLASSIC": "FALCOTTO", "FALCOTTO ACTIVE": "FALCOTTO",
    "FALCOTTO OUTDOOR": "FALCOTTO",
    "FLOWER MOUNTAIN": "FLOWER MOUNTAIN", "FLOWER M.BY NATURINO": "FM BY NAT", "FM ACCESSORI": "FM ACCESSORI",
    "W6YZ ADULTO": "W6YZ", "W6YZ Adulto": "W6YZ", "W6YZ BIMBO": "W6YZ BIMBO", "W6YZ Bimbo": "W6YZ BIMBO",
    "W6YZ Accessori-Abbigliamento": "W6YZ ACCESSORI",
    "VOILE BLANCHE": "VOILE BLANCHE", "VOILE BLANCHE ACCESSORI": "VB ACCESSORI",
    "CANDICE COOPER": "CANDICE COOPER", "Candice Cooper": "CANDICE COOPER",
    "FALCOTTO ROCK": "FALCOTTO", "FALCOTTO NORTH": "FALCOTTO", "NATURINO ROCK": "NATURINO",
    "NATURINO MINI": "NATURINO",
    "FLOWER M.ABBIGLIAMENTO BIMBO": "FM ACCESSORI", "FALCOTTO ABBIGLIAMENTO": "FALCOTTO",
    "FALCOTTO": "FALCOTTO", "FALCOTTO BABY": "FALCOTTO", "FALCOTTO CULLA ABBIGLIAM": "FALCOTTO",
    "NATURINO YOUNG": "NATURINO", "NATURINO ABBIGLIAMENTO": "NATURINO", "NATURINO P_P_G_": "NATURINO",
}

MAP_NATION = {
    "italia": "IT", "italy": "IT", "france": "FR", "germany": "DE", "spain": "ES",
    "united kingdom": "GB", "united states": "US", "stati uniti": "US", "belgium": "BE",
    "denmark": "DK", "españa": "ES", "poland": "PL", "sweden": "SE", "monaco": "FR",
    "nederland": "NL",
    # Alias aggiuntivi (varianti in francese/inglese). Il lookup è case-insensitive
    # (.str.lower() in engine.py): basta UNA voce per variante.
    "allemagne": "DE", "autriche": "AT", "belgique": "BE", "espana": "ES",
    "martinique": "FR", "mc": "FR", "netherland": "NL", "pays-bas": "NL",
    "reunion": "FR", "va": "IT",
}

TASSI_CAMBIO = {
    "EUR": 1.00, "CZK": 24.161, "DKK": 7.4686, "GBP": 0.8796, "PLN": 4.238,
    "SEK": 10.9865, "USD": 1.1614, "CHF": 1.084569,
}

IVA = {"IT": 0.21}

IVA2 = {
    "IT": 0.22, "DE": 0.19, "FR": 0.20, "ES": 0.21, "BE": 0.21,
    "NL": 0.21, "AT": 0.20, "PL": 0.23, "SE": 0.25, "DK": 0.25,
    "CH": 0.081, "GB": 0.20, "US": 0.00, "PT": 0.23, "IE": 0.23,
    "GR": 0.24, "CZ": 0.21, "RO": 0.19, "HR": 0.25, "FI": 0.24,
    "HU": 0.27, "SK": 0.20, "BG": 0.20, "SI": 0.22, "LT": 0.21,
    "LV": 0.21, "EE": 0.22, "LU": 0.17, "CY": 0.19, "MT": 0.18,
    "NO": 0.25, "CA": 0.05, "RS": 0.20,
}

# Codici cliente per la segmentazione del sell-in (tab BUYING) — porting da parseSellInRaw
CODICI_DIRETTI = ["0019243"]
CODICI_ESTERNI = ["0039632"]

# Anno fiscale aziendale: dal 1° novembre al 31 ottobre (es. 01/11/2025 → 31/10/2026)
MESE_INIZIO_ANNO_FISCALE = 11

MESI_IT = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
           "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

IMAGE_URL_TEMPLATE = "https://repository.falc.biz/fal001{img}-1.jpg"

# =========================================================================================
# CARICAMENTO CONFIGURAZIONI PERSISTENTI (data/config_aziendale.json + fallback SQLite/Default)
# =========================================================================================
try:
    from core import settings as _settings
    _active = _settings.load_settings()
    DEFAULT_IVA = float(_active["iva"]["default"])
    IVA = dict(_active["iva"]["aliquote"])
    TASSI_CAMBIO = dict(_active["tassi_cambio"])
    MESE_INIZIO_ANNO_FISCALE = int(_active["anno_fiscale"]["mese_inizio"])
except Exception:
    pass

