"""
Gestione centralizzata e persistente delle configurazioni aziendali.

Permette la configurazione personalizzata di:
1. Anno Fiscale (mese di inizio, default: 11 / Novembre)
2. Aliquote IVA per Nazione + Aliquota di Default (fallback per nazioni non specificate)
3. Tassi di Cambio (per valuta/nazione vs Euro)

Persistenza a doppio livello:
- Primario: file JSON (data/config_aziendale.json). Sopravvive alla cancellazione del DB.
- Secondario: tabella 'impostazioni' nel database SQLite (data/ecombi.db).
- Garanzia: le configurazioni non saranno mai vuote (fallback automatico ai valori predefiniti).
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("data/config_aziendale.json")
DEFAULT_DB_PATH = Path("data/ecombi.db")

# ---------------------------------------------------------------------------------------
# Mappe descrittive (nomi italiani per visualizzazione UI)
# ---------------------------------------------------------------------------------------
NOMI_NAZIONI: dict[str, str] = {
    "IT": "Italia", "DE": "Germania", "FR": "Francia", "ES": "Spagna",
    "GB": "Regno Unito", "US": "Stati Uniti", "BE": "Belgio", "NL": "Paesi Bassi",
    "AT": "Austria", "PL": "Polonia", "SE": "Svezia", "DK": "Danimarca",
    "CH": "Svizzera", "CZ": "Repubblica Ceca", "PT": "Portogallo", "IE": "Irlanda",
    "GR": "Grecia", "RO": "Romania", "HR": "Croazia", "FI": "Finlandia",
    "HU": "Ungheria", "SK": "Slovacchia", "BG": "Bulgaria", "SI": "Slovenia",
    "LT": "Lituania", "LV": "Lettonia", "EE": "Estonia", "LU": "Lussemburgo",
    "CY": "Cipro", "MT": "Malta", "NO": "Norvegia", "CA": "Canada", "RS": "Serbia",
}

NOMI_VALUTE: dict[str, str] = {
    "EUR": "Euro (€)",
    "USD": "Dollaro Statunitense ($)",
    "GBP": "Sterlina Britannica (£)",
    "PLN": "Złoty Polacco (zł)",
    "SEK": "Corona Svedese (kr)",
    "CZK": "Corona Ceca (Kč)",
    "CHF": "Franco Svizzero (CHF)",
    "DKK": "Corona Danese (kr)",
    "CAD": "Dollaro Canadese (CA$)",
    "NOK": "Corona Norvegese (kr)",
}

# Aliquote IVA reali europee (predisposte da IVA2) utilizzabili come preset nella UI
ALIQUOTE_UE_STANDARD: dict[str, float] = {
    "IT": 0.22, "DE": 0.19, "FR": 0.20, "ES": 0.21, "BE": 0.21,
    "NL": 0.21, "AT": 0.20, "PL": 0.23, "SE": 0.25, "DK": 0.25,
    "CH": 0.081, "GB": 0.20, "US": 0.00, "PT": 0.23, "IE": 0.23,
    "GR": 0.24, "CZ": 0.21, "RO": 0.19, "HR": 0.25, "FI": 0.24,
    "HU": 0.27, "SK": 0.20, "BG": 0.20, "SI": 0.22, "LT": 0.21,
    "LV": 0.21, "EE": 0.22, "LU": 0.17, "CY": 0.19, "MT": 0.18,
    "NO": 0.25, "CA": 0.05, "RS": 0.20,
}

# ---------------------------------------------------------------------------------------
# Valori predefiniti di base (garantiti non vuoti)
# ---------------------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, Any] = {
    "anno_fiscale": {
        "mese_inizio": 11,  # 11 = Novembre
    },
    "iva": {
        "default": 0.21,
        "aliquote": {
            "IT": 0.21,
        },
    },
    "tassi_cambio": {
        "EUR": 1.00,
        "CZK": 24.161,
        "DKK": 7.4686,
        "GBP": 0.8796,
        "PLN": 4.238,
        "SEK": 10.9865,
        "USD": 1.1614,
        "CHF": 1.084569,
    },
}


def get_default_settings() -> dict[str, Any]:
    """Restituisce una copia pulita delle configurazioni predefinite."""
    return copy.deepcopy(DEFAULT_SETTINGS)


def validate_settings(data: dict[str, Any] | None) -> dict[str, Any]:
    """
    Valida e normalizza la struttura delle impostazioni.
    Garantisce che nessuna chiave fondamentale manchi mai (mai vuote).
    """
    if not isinstance(data, dict):
        return get_default_settings()

    defaults = get_default_settings()
    out = copy.deepcopy(defaults)

    # 1. Anno Fiscale
    af = data.get("anno_fiscale")
    if isinstance(af, dict) and "mese_inizio" in af:
        try:
            m = int(af["mese_inizio"])
            if 1 <= m <= 12:
                out["anno_fiscale"]["mese_inizio"] = m
        except (ValueError, TypeError):
            pass

    # 2. IVA
    iva = data.get("iva")
    if isinstance(iva, dict):
        if "default" in iva:
            try:
                def_rate = float(iva["default"])
                if 0.0 <= def_rate <= 1.0:
                    out["iva"]["default"] = def_rate
            except (ValueError, TypeError):
                pass

        if "aliquote" in iva and isinstance(iva["aliquote"], dict):
            aliquote_clean: dict[str, float] = {}
            for k, v in iva["aliquote"].items():
                if not k:
                    continue
                k_clean = str(k).strip().upper()
                try:
                    v_clean = float(v)
                    if 0.0 <= v_clean <= 1.0:
                        aliquote_clean[k_clean] = v_clean
                except (ValueError, TypeError):
                    continue
            if aliquote_clean:
                out["iva"]["aliquote"] = aliquote_clean

    # 3. Tassi di Cambio
    tassi = data.get("tassi_cambio")
    if isinstance(tassi, dict):
        tassi_clean: dict[str, float] = {}
        for k, v in tassi.items():
            if not k:
                continue
            k_clean = str(k).strip().upper()
            try:
                v_clean = float(v)
                if v_clean > 0.0:
                    tassi_clean[k_clean] = v_clean
            except (ValueError, TypeError):
                continue
        # EUR deve sempre essere presente e pari a 1.0
        if "EUR" not in tassi_clean:
            tassi_clean["EUR"] = 1.00
        if tassi_clean:
            out["tassi_cambio"] = tassi_clean

    if "aggiornato_il" in data and isinstance(data["aggiornato_il"], str):
        out["aggiornato_il"] = data["aggiornato_il"]

    return out


def _load_from_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return None
            data = json.loads(content)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None


def _load_from_db(db_path: Path) -> dict[str, Any] | None:
    if not db_path.is_file():
        return None
    try:
        with sqlite3.connect(str(db_path)) as conn:
            # Verifica se la tabella esiste
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='impostazioni'"
            )
            if not cur.fetchone():
                return None
            rows = conn.execute("SELECT chiave, valore FROM impostazioni").fetchall()
            if not rows:
                return None
            data: dict[str, Any] = {}
            for chiave, valore in rows:
                try:
                    data[chiave] = json.loads(valore)
                except Exception:
                    pass
            return data if data else None
    except Exception:
        pass
    return None


def _save_to_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _save_to_db(db_path: Path, data: dict[str, Any], iso_now: str) -> None:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS impostazioni (
                    chiave TEXT PRIMARY KEY,
                    valore TEXT NOT NULL,
                    aggiornato_il TEXT NOT NULL
                )
            """)
            for k in ("anno_fiscale", "iva", "tassi_cambio"):
                if k in data:
                    val_str = json.dumps(data[k], ensure_ascii=False)
                    conn.execute(
                        "INSERT OR REPLACE INTO impostazioni (chiave, valore, aggiornato_il) VALUES (?, ?, ?)",
                        (k, val_str, iso_now)
                    )
            conn.commit()
    except Exception:
        pass


def apply_to_config(data: dict[str, Any]) -> None:
    """Aggiorna le variabili globali del modulo core.config a runtime."""
    try:
        from core import config as CFG
        if "anno_fiscale" in data and "mese_inizio" in data["anno_fiscale"]:
            CFG.MESE_INIZIO_ANNO_FISCALE = int(data["anno_fiscale"]["mese_inizio"])
        if "iva" in data:
            if "default" in data["iva"]:
                CFG.DEFAULT_IVA = float(data["iva"]["default"])
            if "aliquote" in data["iva"]:
                CFG.IVA = {str(k).upper(): float(v) for k, v in data["iva"]["aliquote"].items()}
        if "tassi_cambio" in data:
            CFG.TASSI_CAMBIO = {str(k).upper(): float(v) for k, v in data["tassi_cambio"].items()}
    except Exception:
        pass


def load_settings(path: Path | str | None = None, db_path: Path | str | None = None) -> dict[str, Any]:
    """
    Carica le impostazioni attive con fallback a più livelli:
    1. File JSON (data/config_aziendale.json)
    2. Tabella 'impostazioni' in SQLite (data/ecombi.db)
    3. DEFAULT_SETTINGS

    Garantisce che le configurazioni non siano mai vuote e ricrea il file JSON se mancante.
    """
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    dbp = Path(db_path) if db_path else DEFAULT_DB_PATH

    # 1. Prova da JSON
    data = _load_from_json(p)
    if data is not None:
        validated = validate_settings(data)
        apply_to_config(validated)
        return validated

    # 2. Se JSON non trovato o non valido, prova da DB SQLite
    data_db = _load_from_db(dbp)
    if data_db is not None:
        validated = validate_settings(data_db)
        # Ricrea il file JSON per garantire la persistenza autonoma
        try:
            _save_to_json(p, validated)
        except Exception:
            pass
        apply_to_config(validated)
        return validated

    # 3. Fallback ai predefiniti
    validated = get_default_settings()
    try:
        _save_to_json(p, validated)
    except Exception:
        pass
    apply_to_config(validated)
    return validated


def save_settings(data: dict[str, Any], path: Path | str | None = None, db_path: Path | str | None = None) -> dict[str, Any]:
    """
    Salva le impostazioni sia su file JSON che su database SQLite e le applica a core.config.
    """
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    dbp = Path(db_path) if db_path else DEFAULT_DB_PATH

    validated = validate_settings(data)
    now_iso = datetime.now(timezone.utc).isoformat()
    validated["aggiornato_il"] = now_iso

    # Scrittura atomica su JSON
    _save_to_json(p, validated)

    # Scrittura ridondata su SQLite
    _save_to_db(dbp, validated, now_iso)

    # Applicazione runtime
    apply_to_config(validated)

    return validated


def reset_to_defaults(path: Path | str | None = None, db_path: Path | str | None = None) -> dict[str, Any]:
    """Ripristina i valori predefiniti aziendali e salva."""
    defaults = get_default_settings()
    return save_settings(defaults, path=path, db_path=db_path)


# ---------------------# ---------------------------------------------------------------------------------------
# Personalizzazione Widget Homepage (Visibilità e Ordinamento scelti dall'utente)
# ---------------------------------------------------------------------------------------
DEFAULT_HOME_WIDGETS: dict[str, bool] = {
    "calendario_settimanale": True,
    "aree_operative": True,
    "stato_db": True,
}

DEFAULT_HOME_WIDGETS_ORDER: list[str] = [
    "calendario_settimanale",
    "aree_operative",
    "stato_db",
]

METADATA_HOME_WIDGETS: list[dict[str, Any]] = [
    {
        "id": "calendario_settimanale",
        "titolo": "Calendario Presenze Settimanale",
        "descrizione": "Panoramica rapida presenze e ferie dei colleghi (settimana corrente e successiva)",
        "default": True,
    },
    {
        "id": "aree_operative",
        "titolo": "Aree Operative",
        "descrizione": "Riquadri di accesso diretto ai moduli (Analisi Dati, Catalogo, Foto, Ferie)",
        "default": True,
    },
    {
        "id": "stato_db",
        "titolo": "Stato Database & Dati",
        "descrizione": "Metriche di sintesi su articoli, SKU7, marchi e copertura temporale del DB",
        "default": True,
    },
]


def get_user_home_widgets_config(conn: sqlite3.Connection | None, user_email: str | None) -> dict[str, Any]:
    """Recupera la configurazione completa (ordine e visibilità) dei widget per l'utente."""
    config: dict[str, Any] = {
        "ordine": list(DEFAULT_HOME_WIDGETS_ORDER),
        "visibilita": dict(DEFAULT_HOME_WIDGETS),
    }
    import streamlit as st
    try:
        cached = st.session_state.get("home_widgets_prefs")
        if isinstance(cached, dict):
            if "ordine" in cached and isinstance(cached["ordine"], list):
                valid_order = [x for x in cached["ordine"] if x in DEFAULT_HOME_WIDGETS_ORDER]
                for w in DEFAULT_HOME_WIDGETS_ORDER:
                    if w not in valid_order:
                        valid_order.append(w)
                config["ordine"] = valid_order
            if "visibilita" in cached and isinstance(cached["visibilita"], dict):
                config["visibilita"].update(cached["visibilita"])
            elif any(k in DEFAULT_HOME_WIDGETS for k in cached):
                config["visibilita"].update({k: bool(v) for k, v in cached.items() if k in DEFAULT_HOME_WIDGETS})
    except Exception:
        pass

    email_clean = (user_email or "").strip().lower()
    if not email_clean or conn is None:
        return config

    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS utenti_preferenze (
            email TEXT PRIMARY KEY,
            preferenze_json TEXT NOT NULL,
            aggiornato_il TEXT NOT NULL
        );
        """)
        row = conn.execute(
            "SELECT preferenze_json FROM utenti_preferenze WHERE lower(email) = ?",
            (email_clean,)
        ).fetchone()
        if row and row[0]:
            salvati = json.loads(row[0])
            if isinstance(salvati, dict):
                raw_widgets = salvati.get("widgets", salvati)
                if isinstance(raw_widgets, dict):
                    if "ordine" in raw_widgets and isinstance(raw_widgets["ordine"], list):
                        valid_order = [x for x in raw_widgets["ordine"] if x in DEFAULT_HOME_WIDGETS_ORDER]
                        for w in DEFAULT_HOME_WIDGETS_ORDER:
                            if w not in valid_order:
                                valid_order.append(w)
                        config["ordine"] = valid_order
                    if "visibilita" in raw_widgets and isinstance(raw_widgets["visibilita"], dict):
                        config["visibilita"].update(raw_widgets["visibilita"])
                    else:
                        config["visibilita"].update({k: bool(v) for k, v in raw_widgets.items() if k in DEFAULT_HOME_WIDGETS})
            try:
                st.session_state["home_widgets_prefs"] = dict(config)
            except Exception:
                pass
    except Exception:
        pass
    return config


def save_user_home_widgets_config(
    conn: sqlite3.Connection | None,
    user_email: str | None,
    ordine: list[str],
    visibilita: dict[str, bool]
) -> bool:
    """Salva ordine e visibilità dei widget homepage in modo persistente su SQLite e session state."""
    import streamlit as st

    valid_order = [x for x in ordine if x in DEFAULT_HOME_WIDGETS_ORDER]
    for w in DEFAULT_HOME_WIDGETS_ORDER:
        if w not in valid_order:
            valid_order.append(w)

    valid_vis = dict(DEFAULT_HOME_WIDGETS)
    valid_vis.update({k: bool(v) for k, v in visibilita.items() if k in DEFAULT_HOME_WIDGETS})

    nuova_cfg: dict[str, Any] = {
        "ordine": valid_order,
        "visibilita": valid_vis,
    }

    try:
        st.session_state["home_widgets_prefs"] = dict(nuova_cfg)
    except Exception:
        pass

    email_clean = (user_email or "").strip().lower()
    if not email_clean or conn is None:
        return True

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS utenti_preferenze (
            email TEXT PRIMARY KEY,
            preferenze_json TEXT NOT NULL,
            aggiornato_il TEXT NOT NULL
        );
        """)
        payload = json.dumps({"widgets": nuova_cfg})
        conn.execute("""
        INSERT INTO utenti_preferenze (email, preferenze_json, aggiornato_il)
        VALUES (?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            preferenze_json = excluded.preferenze_json,
            aggiornato_il = excluded.aggiornato_il
        """, (email_clean, payload, now_iso))
        conn.commit()
        return True
    except Exception:
        return False


def get_user_home_widgets(conn: sqlite3.Connection | None, user_email: str | None) -> dict[str, bool]:
    """Retrocompatibilità: restituisce il dizionario di visibilità dei widget."""
    cfg = get_user_home_widgets_config(conn, user_email)
    return cfg["visibilita"]


def save_user_home_widgets(conn: sqlite3.Connection | None, user_email: str | None, widgets_config: dict[str, bool]) -> bool:
    """Retrocompatibilità: salva la sola visibilità conservando l'ordine esistente."""
    curr = get_user_home_widgets_config(conn, user_email)
    return save_user_home_widgets_config(conn, user_email, curr["ordine"], widgets_config)
