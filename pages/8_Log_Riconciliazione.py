import streamlit as st

from core import report_builders as rb
from core.ui_helpers import guard_pipeline

st.set_page_config(page_title="Log Riconciliazione", page_icon="🔍", layout="wide")
st.title("🔍 Log Riconciliazione Resi")

pipe = guard_pipeline()

COLS_MATCH = {"ordineId": "Ordine Dataset", "ordineIdResi": "Ordine Resi", "sku13": "SKU13",
              "keyComp": "keyComp", "modalita": "Modalità Match"}
COLS_STANDALONE = {"ordineId": "Ordine Resi", "sku13": "SKU13"}


def blocco(titolo, righe, cols_map):
    st.subheader(titolo)
    df = rb.log_df(righe, cols_map)
    if df.empty:
        st.caption("Nessuna riga.")
    else:
        st.dataframe(df, hide_index=True, use_container_width=True)


anno_corr, anno_prec = st.tabs(["Anno Corrente", "Anno Precedente"])

with anno_corr:
    esito = pipe.esito_resi_current
    blocco("Convertiti (Spedito → Reso)", esito["convertiti"], COLS_MATCH)
    blocco("Duplicati scartati (già Reso in DATASET)", esito["duplicati"], COLS_MATCH)
    standalone_rows = esito["standalone"].to_dict("records") if not esito["standalone"].empty else []
    blocco("Resi Extra (rimborsi non abbinati)", standalone_rows, COLS_STANDALONE)
    blocco("Resi FUORI PERIODO (non applicati)", esito["fuoriPeriodo"], COLS_MATCH)

with anno_prec:
    if pipe.old_data.empty:
        st.info("Carica anche DATASET OLD / RESI OLD nella home per vedere questo log.")
    else:
        esito_old = pipe.esito_resi_old
        blocco("Convertiti (Spedito → Reso)", esito_old["convertiti"], COLS_MATCH)
        blocco("Duplicati scartati (già Reso in DATASET)", esito_old["duplicati"], COLS_MATCH)
        standalone_rows_old = (esito_old["standalone"].to_dict("records")
                                if hasattr(esito_old["standalone"], "empty") and not esito_old["standalone"].empty
                                else [])
        blocco("Resi Extra (rimborsi non abbinati)", standalone_rows_old, COLS_STANDALONE)
        blocco("Resi FUORI PERIODO (non applicati)", esito_old["fuoriPeriodo"], COLS_MATCH)
