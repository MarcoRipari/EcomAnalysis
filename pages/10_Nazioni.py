import streamlit as st

from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, period_labels

st.set_page_config(page_title="Nazioni", page_icon="🌍", layout="wide")
st.title("🌍 Comparativa Nazioni")

pipe = guard_pipeline()

y_curr, y_old = period_labels(2)
ha_confronto = not pipe.old_data.empty
st.caption(
    f"**{y_curr}**: {st.session_state.get('periodo_a_label', '—')}"
    + (f" · **{y_old}**: {st.session_state.get('periodo_b_label', '—')}" if ha_confronto else "")
)

current_data = pipe.current_data
old_data = pipe.old_data
standalone_current = pipe.esito_resi_current["standalone"]
standalone_old = pipe.esito_resi_old["standalone"]

opzioni_nazioni = rb.nazioni_disponibili(current_data, old_data)
if not opzioni_nazioni:
    st.caption("Nessuna nazione trovata nel periodo selezionato.")
    st.stop()

nazioni_scelte = st.multiselect("Nazioni da comparare", opzioni_nazioni, default=opzioni_nazioni[:5])
if not nazioni_scelte:
    st.info("Seleziona almeno una nazione.")
    st.stop()

st.divider()
st.subheader(f"📊 KPI per nazione — {y_curr}")
tabella_curr = rb.nazioni_metrics(current_data, standalone_current, nazioni_scelte)
st.dataframe(tabella_curr, hide_index=True, use_container_width=True, column_config={
    "Fatturato Netto Totale": currency_col(),
    "% Reso": percent_col(),
    "Totale Ordini": number_col(), "Totale Paia Nette": number_col(),
    "Paia Rese (spedito nel range)": number_col(), "Paia Rese (spedito fuori range)": number_col(),
})

if ha_confronto:
    st.subheader(f"📊 KPI per nazione — {y_old}")
    tabella_old = rb.nazioni_metrics(old_data, standalone_old, nazioni_scelte)
    st.dataframe(tabella_old, hide_index=True, use_container_width=True, column_config={
        "Fatturato Netto Totale": currency_col(),
        "% Reso": percent_col(),
        "Totale Ordini": number_col(), "Totale Paia Nette": number_col(),
        "Paia Rese (spedito nel range)": number_col(), "Paia Rese (spedito fuori range)": number_col(),
    })

    st.subheader("📈 Variazione % fatturato netto totale")
    merge = tabella_curr[["Nazione", "Fatturato Netto Totale"]].merge(
        tabella_old[["Nazione", "Fatturato Netto Totale"]], on="Nazione", suffixes=(f" {y_curr}", f" {y_old}"))
    merge["VAR%"] = merge.apply(
        lambda r: rb.var_pct(r[f"Fatturato Netto Totale {y_curr}"], r[f"Fatturato Netto Totale {y_old}"]), axis=1)
    st.dataframe(merge, hide_index=True, use_container_width=True, column_config={
        f"Fatturato Netto Totale {y_curr}": currency_col(), f"Fatturato Netto Totale {y_old}": currency_col(),
        "VAR%": percent_col(),
    })

st.divider()
st.subheader("🏷️ Share del fatturato per brand, per nazione")
tabs = st.tabs(nazioni_scelte)
for tab, naz in zip(tabs, nazioni_scelte):
    with tab:
        col1, col2 = st.columns(2) if ha_confronto else (st.container(), None)
        with col1:
            st.caption(y_curr)
            share_curr = rb.nazioni_brand_share(current_data, naz)
            st.dataframe(share_curr, hide_index=True, use_container_width=True, column_config={
                "Fatturato Netto": currency_col(), "Share %": percent_col(),
            })
        if ha_confronto:
            with col2:
                st.caption(y_old)
                share_old = rb.nazioni_brand_share(old_data, naz)
                st.dataframe(share_old, hide_index=True, use_container_width=True, column_config={
                    "Fatturato Netto": currency_col(), "Share %": percent_col(),
                })
