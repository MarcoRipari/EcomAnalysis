import streamlit as st
import pandas as pd

from core import report_builders as rb
from core import metrics as met
from core import aggregations as agg
from core.design_system import page_setup, section, data_table, metric_cards, empty_state, it_num
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels

page_setup("Analisi Resi", "🔄",
           "Monitoraggio analitico dei resi: tassi di reso per brand, marketplace, nazione e articoli critici")

pipe = guard_pipeline()
current_data = pipe.current_data
st_curr = pipe.resi_fp_current

# KPI globali sui resi
kpi_tot = met.compute_channel_kpi(current_data, st_curr)
fatt_reso_tot = (current_data["nettoReso"].sum() if not current_data.empty else 0.0) + (st_curr["nettoReso"].sum() if not st_curr.empty else 0.0)

metric_cards([
    {"label": "Paia Rese Totali", "value": it_num(kpi_tot["paiaRes"])},
    {"label": "% Reso (su Paia Spedite)", "value": f"{it_num(kpi_tot['percReso'] * 100, 1)}%"},
    {"label": "Fatturato Rimborsato Totale", "value": f"{it_num(fatt_reso_tot, 2)} €"},
    {"label": "% Reso (su Valore Spedito)", "value": f"{it_num(kpi_tot['percResoValore'] * 100, 1)}%"},
    {"label": "Paia rese di vendite del periodo", "value": it_num(kpi_tot["paiaResePeriodo"])},
    {"label": "Paia rese di vendite fuori periodo", "value": it_num(kpi_tot["paiaReseFuoriPeriodo"])},
])

st.divider()

tab_collezioni, tab_canali, tab_articoli = st.tabs([
    "🏷️ Resi per Brand e Collezione",
    "🌐 Resi per Marketplace e Nazione",
    "⚠️ Top Articoli Critici per Reso",
])

with tab_collezioni:
    section("Stato dei Resi per Brand / Collezione",
            caption="Soglia benchmark: 30% · 🟢 <20% Ottimo · 🔵 20-30% Stabile · 🟡 30-40% Monitorare · 🟠 40-50% Elevato · 🔴 >50% Critico")
    df_status = rb.resi_status(current_data, st_curr)
    if not df_status.empty:
        data_table(df_status, {
            "% Reso": percent_col(),
            "Fatturato": currency_col(),
            "Paia Spedite": number_col(),
            "Paia Rese": number_col(),
        })
    else:
        empty_state("Nessun dato per il calcolo dello stato resi.")

with tab_canali:
    col_mkp, col_naz = st.columns(2)
    with col_mkp:
        section("Tasso di Reso per Marketplace")
        agg_mkp = agg.aggregate_by_key(current_data, "mkp", st_curr)
        df_mkp_resi = []
        for mkp, dati in agg_mkp.get("map", {}).items():
            paia_sped = dati.get("paiaSpedite", 0.0)
            paia_res = dati.get("paiaRese", 0.0)
            p_res = (paia_res / paia_sped) if paia_sped > 0 else 0.0
            df_mkp_resi.append({
                "Marketplace": mkp,
                "Paia Spedite": paia_sped,
                "Paia Rese": paia_res,
                "% Reso": p_res,
                "Fatturato": dati.get("fatturatoNetto", 0.0),
            })
        if df_mkp_resi:
            df_mkp_resi_df = pd.DataFrame(df_mkp_resi).sort_values("% Reso", ascending=False).reset_index(drop=True)
            data_table(df_mkp_resi_df, {
                "% Reso": percent_col(),
                "Paia Spedite": number_col(),
                "Paia Rese": number_col(),
                "Fatturato": currency_col(),
            })

    with col_naz:
        section("Tasso di Reso per Nazione")
        agg_naz = agg.aggregate_by_key(current_data, "nazione", st_curr)
        df_naz_resi = []
        for naz, dati in agg_naz.get("map", {}).items():
            paia_sped = dati.get("paiaSpedite", 0.0)
            paia_res = dati.get("paiaRese", 0.0)
            p_res = (paia_res / paia_sped) if paia_sped > 0 else 0.0
            df_naz_resi.append({
                "Nazione": naz,
                "Paia Spedite": paia_sped,
                "Paia Rese": paia_res,
                "% Reso": p_res,
                "Fatturato": dati.get("fatturatoNetto", 0.0),
            })
        if df_naz_resi:
            df_naz_resi_df = pd.DataFrame(df_naz_resi).sort_values("% Reso", ascending=False).reset_index(drop=True)
            data_table(df_naz_resi_df, {
                "% Reso": percent_col(),
                "Paia Spedite": number_col(),
                "Paia Rese": number_col(),
                "Fatturato": currency_col(),
            })

with tab_articoli:
    section("Top 20 Articoli con Maggior Fatturato Perso in Resi",
            caption="Articoli ordinati per totale valore rimborsato (€) decrescente")
    y_curr, _ = period_labels(1)[0], None
    top_art = rb.top_articoli_dashboard(current_data, pipe.anagrafica, top_n=5000, resi_fp_data=st_curr)
    if not top_art.empty:
        top_art_critici = top_art.sort_values("Valore Reso", ascending=False).head(20).reset_index(drop=True)
        data_table(top_art_critici, {
            "Foto": image_col(),
            "Valore Reso": currency_col(),
            "% Reso": percent_col(),
            "Fatturato": currency_col(),
            "Paia Rese": number_col(),
            "Paia Spedite": number_col(),
        })
    else:
        empty_state("Nessun articolo rilevato.")
