import streamlit as st

from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col

st.set_page_config(page_title="Taglie per Brand", page_icon="👟", layout="wide")
st.title("👟 Analisi Taglie per Brand")

pipe = guard_pipeline()

tables = rb.taglie_tables(pipe.current_data)
if not tables:
    st.caption("Nessun dato.")
    st.stop()

brand_scelto = st.selectbox("Brand", list(tables.keys()))

cols = st.columns(len(tables[brand_scelto]) or 1)
for col, (gruppo, df) in zip(cols, tables[brand_scelto].items()):
    with col:
        st.subheader(f"👥 {gruppo}")
        st.dataframe(df, hide_index=True, use_container_width=True, column_config={
            "Paia Nette": number_col(),
            df.columns[2]: percent_col(),  # "% su <gruppo>"
            "% Reso": percent_col(),
            "Fatturato Netto": currency_col(),
        })
