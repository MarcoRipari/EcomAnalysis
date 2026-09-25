import streamlit as st

from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col

st.set_page_config(page_title="Analisi Resi", page_icon="🔄", layout="wide")
st.title("🔄 Analisi Resi Completa — Anno Corrente")

pipe = guard_pipeline()

df = rb.resi_status(pipe.current_data)
if df.empty:
    st.caption("Nessun dato.")
    st.stop()

st.caption("Soglia di riferimento: 30% (🟢 Ottimo · 🔵 Stabile · 🟡 Monitorare · 🟠 Pessimo · 🔴 Critico)")
st.dataframe(df, hide_index=True, use_container_width=True, height=650, column_config={
    "% Reso": percent_col(), "Fatturato Netto": currency_col(),
    "Paia Spedite": number_col(), "Paia Rese": number_col(),
})
