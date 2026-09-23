import streamlit as st

from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, years

st.set_page_config(page_title="Y2Y Codici", page_icon="🔢", layout="wide")
st.title("🔢 Comparativa Y2Y — Codici Articolo (SKU7)")

pipe = guard_pipeline()
y_curr, y_old = years()

if pipe.old_data.empty:
    st.warning("Carica anche **DATASET OLD** e **RESI OLD** nella home per abilitare questo report.")
    st.stop()

df = rb.comparativa_codici(pipe.current_data, pipe.old_data, pipe.anagrafica, y_curr, y_old)

filtro = st.text_input("🔎 Filtra per codice, collezione o descrizione")
if filtro:
    mask = df.apply(lambda r: filtro.lower() in " ".join(str(v) for v in r.values).lower(), axis=1)
    df = df[mask]

st.caption(f"{len(df):,} codici articolo".replace(",", "."))
st.dataframe(df, hide_index=True, use_container_width=True, height=650, column_config={
    "Foto": image_col(),
    f"Fatt. Net {y_curr}": currency_col(), f"Fatt. Net {y_old}": currency_col(),
    f"% Reso {y_curr}": percent_col(), f"% Reso {y_old}": percent_col(),
    "VAR% FATT": percent_col(),
    f"Paia Net {y_curr}": number_col(), f"Paia Net {y_old}": number_col(),
})
