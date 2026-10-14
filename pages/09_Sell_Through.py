import streamlit as st

from core import sellthrough as st_mod
from core.design_system import page_setup, data_table, empty_state
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col

page_setup("Sell-Through", None)

pipe = guard_pipeline()

buying_file = st.file_uploader("File BUYING (sell-in)", type=["csv"])

livello = st.radio("Dettaglio Analisi", ["Articolo (7)", "Articolo/Variante (9)", "Articolo/Variante/Colore (13)"],
                    horizontal=True)
lunghezza = {"Articolo (7)": 7, "Articolo/Variante (9)": 9, "Articolo/Variante/Colore (13)": 13}[livello]

if buying_file is None:
    empty_state("Carica il file CSV di sell-in (BUYING) per generare l'analisi di sell-through.")
    st.stop()

try:
    df_buying = st_mod.read_buying_csv(buying_file)
    sell_in_raw = st_mod.parse_sell_in_raw(df_buying, pipe.perimetro)
except Exception as e:
    st.exception(e)
    st.stop()

if not sell_in_raw:
    st.warning("Nessuna riga valida trovata nel BUYING per il perimetro selezionato.")
    st.stop()

df = st_mod.generate_sell_through(pipe.current_data, sell_in_raw, pipe.anagrafica, lunghezza)
if df.empty:
    st.warning("Nessuna corrispondenza fra BUYING e DATASET su questo livello di aggregazione.")
    st.stop()

st.caption(f"{len(df):,} codici in sell-through".replace(",", "."))

currency_cols = [c for c in df.columns if c.startswith("Fatturato") or c.startswith("P.Medio")]
percent_cols = [c for c in df.columns if c.startswith("ST%") or c.startswith("% su")]
number_cols = [c for c in df.columns if c.startswith("Vend.") or c.startswith("Resid.") or c == "Acq."]

col_config = {"Foto": image_col()}
col_config.update({c: currency_col() for c in currency_cols})
col_config.update({c: percent_col() for c in percent_cols})
col_config.update({c: number_col() for c in number_cols})

data_table(df, col_config)
