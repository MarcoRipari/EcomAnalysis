import streamlit as st

from core import aggregations as agg
from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, years

st.set_page_config(page_title="Y2Y Collezioni", page_icon="🌳", layout="wide")
st.title("🌳 Comparativa Y2Y — Alberatura Collezioni")

pipe = guard_pipeline()
y_curr, y_old = years()

if pipe.old_data.empty:
    st.warning("Carica anche **DATASET OLD** e **RESI OLD** nella home per abilitare questo report.")
    st.stop()

current_data, old_data = pipe.current_data, pipe.old_data


def skip_clz(key_name, row):
    if key_name == "clzOriginale":
        orig = str(row.get("clzOriginale") or "").strip().upper()
        mapv = str(row.get("clzMappata") or "").strip().upper()
        return (not orig) or orig == "ALTRO" or orig == mapv
    return False


def render_tree(title, keys, level_names, skip=None):
    st.subheader(title)
    curr_tree = agg.aggregate_hierarchical_custom(current_data, keys, skip)
    old_tree = agg.aggregate_hierarchical_custom(old_data, keys, skip)
    df = rb.flatten_hierarchical_table(curr_tree, old_tree, level_names)
    if df.empty:
        st.caption("Nessun dato.")
        return
    st.dataframe(
        df.drop(columns="Depth"), hide_index=True, use_container_width=True, height=min(700, 40 + 35 * len(df)),
        column_config={
            "Fatt. Netto Curr": currency_col(f"Fatt. Netto {y_curr}"),
            "Fatt. Netto Old": currency_col(f"Fatt. Netto {y_old}"),
            "% Tot Curr": percent_col(f"% Tot {y_curr}"), "% Tot Old": percent_col(f"% Tot {y_old}"),
            "% Reso Curr": percent_col(f"% Reso {y_curr}"), "% Reso Old": percent_col(f"% Reso {y_old}"),
            "VAR% FATT": percent_col(), "VAR% PAIA": percent_col(),
            "Paia Net Curr": number_col(f"Paia Net {y_curr}"), "Paia Net Old": number_col(f"Paia Net {y_old}"),
        },
    )


render_tree("1. Analisi per Brand / Collezione", ["clzMappata", "clzOriginale"], ["Brand", "Collezione Originale"])
render_tree("2. Dettaglio per Marketplace (4 livelli)", ["clzMappata", "mkp", "nazione", "clzOriginale"],
            ["Brand", "Marketplace", "Nazione", "Collezione"], skip_clz)
render_tree("3. Dettaglio per Nazione (4 livelli)", ["clzMappata", "nazione", "mkp", "clzOriginale"],
            ["Brand", "Nazione", "Marketplace", "Collezione"], skip_clz)
