import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core import config as CFG
from core import settings
from core.design_system import page_setup, section

page_setup(
    "Configurazioni", "⚙️",
    "Parametri aziendali modificabili: Anno Fiscale, Aliquote IVA per Nazione e Tassi di Cambio"
)

# ---------------------------------------------------------------------------------------
# Caricamento configurazioni attive
# ---------------------------------------------------------------------------------------
impostazioni = settings.load_settings()

mese_inizio_corrente = int(impostazioni["anno_fiscale"]["mese_inizio"])
iva_default_corrente = float(impostazioni["iva"]["default"])
aliquote_correnti = dict(impostazioni["iva"]["aliquote"])
tassi_correnti = dict(impostazioni["tassi_cambio"])

# Gestione reset / precaricamento tramite session_state
if "cfg_aliquote_seed" not in st.session_state:
    st.session_state["cfg_aliquote_seed"] = None

if "cfg_tassi_seed" not in st.session_state:
    st.session_state["cfg_tassi_seed"] = None

# Tab principali di configurazione
tab_fiscale, tab_iva, tab_cambio, tab_backup = st.tabs([
    "📅 Anno Fiscale",
    "💶 Aliquote IVA (per Nazione)",
    "💱 Tassi di Cambio (per Valuta)",
    "💾 Stato & Backup",
])

# =======================================================================================
# TAB 1: ANNO FISCALE
# =======================================================================================
with tab_fiscale:
    section("1. Mese di Inizio Anno Fiscale",
            caption="Imposta il mese in cui comincia l'anno fiscale aziendale. Questa data determina "
                    "le etichette di periodo (es. 25/26), i confronti Y2Y e gli intervalli caricati all'avvio.")

    c_fisc1, c_fisc2 = st.columns([3, 4])
    with c_fisc1:
        opzioni_mesi = list(range(1, 13))
        mese_scelto = st.selectbox(
            "Mese di inizio",
            options=opzioni_mesi,
            index=mese_inizio_corrente - 1,
            format_func=lambda m: f"{m:02d} — {CFG.MESI_IT[m - 1]}",
            help="11 = Novembre (aziendale Falc: 01/11 → 31/10). 01 = Anno solare (01/01 → 31/12).",
            key="cfg_mese_inizio",
        )

    with c_fisc2:
        nome_mese_inizio = CFG.MESI_IT[mese_scelto - 1]
        mese_fine = (mese_scelto - 2) % 12 + 1
        nome_mese_fine = CFG.MESI_IT[mese_fine - 1]
        st.info(
            f"📌 **Periodicità attiva:** con inizio a **{nome_mese_inizio}**, l'anno fiscale si estende dal "
            f"**1° {nome_mese_inizio}** all'ultimo giorno di **{nome_mese_fine}** dell'anno successivo.\n\n"
            f"Ad esempio, l'anno fiscale **25/26** decorre dal **01/{mese_scelto:02d}/2025** al "
            f"fine mese di **{nome_mese_fine} 2026**."
        )

# =======================================================================================
# TAB 2: ALIQUOTE IVA PER NAZIONE
# =======================================================================================
with tab_iva:
    section("2. Aliquote IVA per Nazione",
            caption="L'aliquota IVA viene utilizzata per calcolare il fatturato netto da quello lordo: "
                    "Fatturato Netto = Fatturato Lordo / (1 + Aliquota).")

    c_def1, c_def2 = st.columns([3, 4])
    with c_def1:
        nuovo_default_iva_perc = st.number_input(
            "Aliquota IVA di Default (Fallback %)",
            min_value=0.0,
            max_value=100.0,
            value=float(iva_default_corrente * 100.0),
            step=0.5,
            format="%.2f",
            help="Applicata automaticamente a tutte le nazioni non esplicitamente elencate nella tabella.",
            key="cfg_default_iva_input",
        )

    with c_def2:
        st.caption(
            "💡 **Aliquota di fallback**: quando una vendita appartiene a un paese non specificato nella "
            f"tabella sottostante, verrà scorporata al **{nuovo_default_iva_perc:.2f}%**."
        )

    st.write("")

    # Costruzione DataFrame per l'editor
    if st.session_state["cfg_aliquote_seed"] is not None:
        source_aliquote = st.session_state["cfg_aliquote_seed"]
    else:
        source_aliquote = aliquote_correnti

    righe_iva = []
    for naz, val in sorted(source_aliquote.items()):
        righe_iva.append({
            "Nazione": str(naz).upper(),
            "Aliquota (%)": float(val * 100.0),
            "Nome Paese": settings.NOMI_NAZIONI.get(str(naz).upper(), ""),
        })

    df_iva_seed = pd.DataFrame(righe_iva)
    if df_iva_seed.empty:
        df_iva_seed = pd.DataFrame(columns=["Nazione", "Aliquota (%)", "Nome Paese"])

    c_btn1, c_btn2, _ = st.columns([3, 3, 4])
    with c_btn1:
        if st.button("📋 Precarica tutte le nazioni UE (aliquote standard)", help="Inserisce le aliquote IVA standard dei paesi europei"):
            st.session_state["cfg_aliquote_seed"] = copy.deepcopy(settings.ALIQUOTE_UE_STANDARD)
            st.rerun()
    with c_btn2:
        if st.button("↩️ Ripristina tabella IVA salvata", help="Annulla le modifiche non salvate alla tabella IVA"):
            st.session_state["cfg_aliquote_seed"] = None
            st.rerun()

    editor_iva_df = st.data_editor(
        df_iva_seed,
        num_rows="dynamic",
        width="stretch",
        key="cfg_editor_iva",
        column_config={
            "Nazione": st.column_config.TextColumn(
                "Codice Nazione (ISO)",
                max_chars=2,
                required=True,
                help="Codice ISO 2 lettere (es. IT, DE, FR, ES, GB, US...)",
            ),
            "Aliquota (%)": st.column_config.NumberColumn(
                "Aliquota IVA (%)",
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                format="%.2f%%",
                required=True,
                help="Valore in percentuale (es. 22.00 per il 22%)",
            ),
            "Nome Paese": st.column_config.TextColumn(
                "Nome Paese (opzionale)",
                help="Nome descrittivo per promemoria (es. Italia, Germania)",
            ),
        },
    )

# =======================================================================================
# TAB 3: TASSI DI CAMBIO VALUTA
# =======================================================================================
with tab_cambio:
    section("3. Tassi di Cambio Valuta",
            caption="Tassi di conversione delle valute estere verso l'Euro: Lordo EUR = Importo Valuta / Tasso. "
                    "Un tasso di 1.1614 per USD indica che 1 EUR = 1.1614 USD.")

    if st.session_state["cfg_tassi_seed"] is not None:
        source_tassi = st.session_state["cfg_tassi_seed"]
    else:
        source_tassi = tassi_correnti

    righe_cambio = []
    for val, tasso in sorted(source_tassi.items()):
        righe_cambio.append({
            "Valuta": str(val).upper(),
            "Tasso vs EUR": float(tasso),
            "Descrizione / Nazione": settings.NOMI_VALUTE.get(str(val).upper(), ""),
        })

    df_cambio_seed = pd.DataFrame(righe_cambio)
    if df_cambio_seed.empty:
        df_cambio_seed = pd.DataFrame(columns=["Valuta", "Tasso vs EUR", "Descrizione / Nazione"])

    c_btn_c1, _ = st.columns([3, 7])
    with c_btn_c1:
        if st.button("↩️ Ripristina tassi salvati", help="Annulla le modifiche non salvate ai tassi"):
            st.session_state["cfg_tassi_seed"] = None
            st.rerun()

    editor_cambio_df = st.data_editor(
        df_cambio_seed,
        num_rows="dynamic",
        width="stretch",
        key="cfg_editor_cambio",
        column_config={
            "Valuta": st.column_config.TextColumn(
                "Codice Valuta (3 lettere)",
                max_chars=3,
                required=True,
                help="Codice valuta (es. EUR, USD, GBP, PLN, SEK, CZK, CHF...)",
            ),
            "Tasso vs EUR": st.column_config.NumberColumn(
                "Tasso vs EUR (1 EUR = X valuta)",
                min_value=0.000001,
                step=0.01,
                format="%.4f",
                required=True,
                help="Quantità di valuta estera corrispondente a 1 Euro",
            ),
            "Descrizione / Nazione": st.column_config.TextColumn(
                "Descrizione / Nazione",
                help="Descrizione amichevole della valuta o del mercato",
            ),
        },
    )

# =======================================================================================
# TAB 4: STATO & BACKUP
# =======================================================================================
with tab_backup:
    section("4. Stato Persistenza & Ridondanza",
            caption="Le configurazioni sono protette contro cancellazioni accidentali del database.")

    json_path = settings.DEFAULT_CONFIG_PATH
    db_path = settings.DEFAULT_DB_PATH

    c_st1, c_st2 = st.columns(2)
    with c_st1:
        if json_path.is_file():
            stat_j = json_path.stat()
            dt_j = datetime.fromtimestamp(stat_j.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            st.success(f"📄 **File JSON Config:** `{json_path}`\n\n- Stato: **Attivo e persistente**\n- Ultima modifica: **{dt_j}**\n- Dimensione: **{stat_j.st_size} byte**")
        else:
            st.warning(f"📄 **File JSON:** `{json_path}` non ancora creato sul disco.")

    with c_st2:
        if db_path.is_file():
            st.info(f"🗄️ **Database SQLite:** `{db_path}`\n\n- Tabella di backup: **`impostazioni`**\n- Sincronizzazione: **Attiva** (duplice salvataggio)")
        else:
            st.info(f"🗄️ **Database SQLite:** nessun DB `data/ecombi.db` rilevato. I file JSON proteggono tutte le impostazioni.")

    st.write("")
    st.markdown(
        "> [!TIP]\n"
        "> **Sicurezza dei dati:** se il database SQLite viene ricreato o cancellato, "
        "> il file `data/config_aziendale.json` ripristina automaticamente tutte le personalizzazioni. "
        "> Le configurazioni aziendali non andranno mai perse e non risulteranno mai vuote."
    )

    # Download / Upload di backup
    json_bytes = json.dumps(impostazioni, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button(
        "📥 Scarica copia di backup configurazioni (.json)",
        data=json_bytes,
        file_name="config_aziendale_backup.json",
        mime="application/json",
    )

# =======================================================================================
# BARRA AZIONI: SALVA & RIPRISTINA
# =======================================================================================
st.divider()

col_salva, col_reset, _ = st.columns([2, 2, 4])

with col_salva:
    if st.button("💾 Salva Configurazioni", type="primary", use_container_width=True):
        # 1. Raccoglie dati IVA dall'editor
        aliquote_finali: dict[str, float] = {}
        if editor_iva_df is not None and not editor_iva_df.empty:
            for _, r in editor_iva_df.iterrows():
                naz_raw = str(r.get("Nazione", "")).strip().upper()
                ali_raw = r.get("Aliquota (%)")
                if naz_raw and pd.notna(ali_raw):
                    try:
                        v = float(ali_raw) / 100.0
                        if 0.0 <= v <= 1.0:
                            aliquote_finali[naz_raw] = round(v, 4)
                    except (ValueError, TypeError):
                        pass

        # Garanzia minima
        if not aliquote_finali:
            aliquote_finali["IT"] = 0.21

        # 2. Raccoglie dati Tassi dall'editor
        tassi_finali: dict[str, float] = {}
        if editor_cambio_df is not None and not editor_cambio_df.empty:
            for _, r in editor_cambio_df.iterrows():
                val_raw = str(r.get("Valuta", "")).strip().upper()
                tasso_raw = r.get("Tasso vs EUR")
                if val_raw and pd.notna(tasso_raw):
                    try:
                        t = float(tasso_raw)
                        if t > 0.0:
                            tassi_finali[val_raw] = round(t, 6)
                    except (ValueError, TypeError):
                        pass

        # Garanzia EUR
        tassi_finali["EUR"] = 1.00

        # 3. Assemblaggio payload completo
        payload: dict = {
            "anno_fiscale": {
                "mese_inizio": int(mese_scelto),
            },
            "iva": {
                "default": round(float(nuovo_default_iva_perc) / 100.0, 4),
                "aliquote": aliquote_finali,
            },
            "tassi_cambio": tassi_finali,
        }

        # 4. Salvataggio persistente e applicazione
        settings.save_settings(payload)

        # Reset flag temporanei in session state
        st.session_state["cfg_aliquote_seed"] = None
        st.session_state["cfg_tassi_seed"] = None

        # Invalida pipeline in session state per ricalcolare i dati con le nuove impostazioni
        st.session_state["rigenera_pipeline"] = True
        st.session_state.pop("pipeline", None)
        st.session_state.pop("sel_periodo_a", None)
        st.session_state.pop("sel_periodo_b", None)

        st.success("✅ Configurazioni salvate con successo su file JSON e nel database!")
        st.rerun()

with col_reset:
    if st.button("🔄 Ripristina Predefiniti", use_container_width=True, help="Ripristina tutte le configurazioni ai valori di fabbrica"):
        settings.reset_to_defaults()
        st.session_state["cfg_aliquote_seed"] = None
        st.session_state["cfg_tassi_seed"] = None
        st.session_state["rigenera_pipeline"] = True
        st.session_state.pop("pipeline", None)
        st.session_state.pop("sel_periodo_a", None)
        st.session_state.pop("sel_periodo_b", None)
        st.success("🔄 Configurazioni ripristinate ai valori predefiniti.")
        st.rerun()
