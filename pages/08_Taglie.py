import streamlit as st

from core import report_builders as rb
from core.design_system import page_setup, section, data_table, empty_state
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col

page_setup("Taglie per Brand", None)

pipe = guard_pipeline()
current_data = pipe.current_data
st_curr = pipe.resi_fp_current

tables = rb.taglie_tables(current_data, st_curr)
if not tables:
    empty_state("Nessun dato sulle taglie rilevato nel periodo selezionato.")
    st.stop()

col_sel, _ = st.columns([1, 2])
with col_sel:
    brand_scelto = st.selectbox("Seleziona Brand", list(tables.keys()))

st.divider()

gruppi = tables.get(brand_scelto, {})
if not gruppi:
    empty_state(f"Nessun dato per il brand {brand_scelto}.")
else:
    for gruppo, df in gruppi.items():
        section(f"Genere / Categoria: {gruppo}")
        col_share = df.columns[2] if len(df.columns) > 2 else "% Share"
        data_table(df, {
            "Paia Nette": number_col(),
            col_share: percent_col(),
            "% Reso": percent_col(),
            "Fatturato": currency_col(),
        })
