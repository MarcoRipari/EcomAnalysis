import streamlit as st

from core import aggregations as agg
from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels

st.set_page_config(page_title="Carryover", page_icon="♻️", layout="wide")
st.title("♻️ Carryover Y2Y — Articoli venduti in entrambe le stagioni")

pipe = guard_pipeline()
y_curr, y_old = period_labels(2)

if pipe.old_data.empty:
    st.warning("Carica anche **DATASET OLD** e **RESI OLD** nella home per abilitare questo report.")
    st.stop()

carry = agg.filter_carryover_data(pipe.current_data, pipe.old_data)
curr_co, old_co = carry["curr"], carry["old"]
st.caption(f"{curr_co['sku13'].nunique() if not curr_co.empty else 0} SKU13 in carryover fra le due stagioni.")

tab_albero, tab_codici = st.tabs(["🌳 Alberatura Brand/Collezione", "🔢 Codici Articolo"])


def skip_clz(key_name, row):
    if key_name == "clzOriginale":
        orig = str(row.get("clzOriginale") or "").strip().upper()
        mapv = str(row.get("clzMappata") or "").strip().upper()
        return (not orig) or orig == "ALTRO" or orig == mapv
    return False


with tab_albero:
    def render_tree(title, keys, level_names, skip=None):
        st.subheader(title)
        curr_tree = agg.aggregate_hierarchical_custom(curr_co, keys, skip)
        old_tree = agg.aggregate_hierarchical_custom(old_co, keys, skip)
        df = rb.flatten_hierarchical_table(curr_tree, old_tree, level_names)
        if df.empty:
            st.caption("Nessun dato.")
            return
        st.dataframe(df.drop(columns="Depth"), hide_index=True, use_container_width=True,
                     height=min(700, 40 + 35 * len(df)), column_config={
                         "Fatt. Netto Curr": currency_col(f"Fatt. Netto {y_curr}"),
                         "Fatt. Netto Old": currency_col(f"Fatt. Netto {y_old}"),
                         "% Tot Curr": percent_col(f"% Tot {y_curr}"), "% Tot Old": percent_col(f"% Tot {y_old}"),
                         "% Reso Curr": percent_col(f"% Reso {y_curr}"), "% Reso Old": percent_col(f"% Reso {y_old}"),
                         "VAR% FATT": percent_col(), "VAR% PAIA": percent_col(),
                         "Paia Net Curr": number_col(f"Paia Net {y_curr}"),
                         "Paia Net Old": number_col(f"Paia Net {y_old}"),
                     })

    render_tree("Carryover Brand / Collezione", ["clzMappata", "clzOriginale"], ["Brand", "Collezione Originale"])
    render_tree("Carryover Marketplace", ["clzMappata", "mkp", "nazione", "clzOriginale"],
                ["Brand", "Marketplace", "Nazione", "Collezione"], skip_clz)
    render_tree("Carryover Nazione", ["clzMappata", "nazione", "mkp", "clzOriginale"],
                ["Brand", "Nazione", "Marketplace", "Collezione"], skip_clz)

with tab_codici:
    df = rb.comparativa_codici(curr_co, old_co, pipe.anagrafica, y_curr, y_old)
    st.dataframe(df, hide_index=True, use_container_width=True, height=650, column_config={
        "Foto": image_col(),
        f"Fatt. Net {y_curr}": currency_col(), f"Fatt. Net {y_old}": currency_col(),
        f"% Reso {y_curr}": percent_col(), f"% Reso {y_old}": percent_col(),
        "VAR% FATT": percent_col(),
        f"Paia Net {y_curr}": number_col(), f"Paia Net {y_old}": number_col(),
    })
