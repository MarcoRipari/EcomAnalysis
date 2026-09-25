import plotly.express as px
import streamlit as st

from core import metrics as met
from core import aggregations as agg
from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, years

st.set_page_config(page_title="Y2Y Generale", page_icon="📈", layout="wide")
st.title("📈 Comparativa Year-over-Year — Generale")

pipe = guard_pipeline()
y_curr, y_old = years()

if pipe.old_data.empty:
    st.warning("Carica anche **DATASET OLD** e **RESI OLD** nella home per abilitare i confronti Y2Y.")
    st.stop()

current_data, old_data = pipe.current_data, pipe.old_data
resi_standalone_current = pipe.esito_resi_current["standalone"]
resi_standalone_old = pipe.esito_resi_old["standalone"]

diretto_pred = lambda df: df["tipoSpedizione"] == "DIRETTO"
zalando_pred = lambda df: df["ordineId"].str.contains("_ZFS", na=False) if not df.empty else df.index < 0


def show_kpi_block(title, kc, ko):
    st.subheader(title)
    block = rb.kpi_block(kc, ko, y_curr, y_old)
    if block is None:
        st.caption("Nessun dato rilevato nel periodo/perimetro selezionato.")
        return
    st.dataframe(block, hide_index=True, use_container_width=True, column_config={
        "Var % Y2Y": percent_col(),
    })


kpi_c = met.compute_channel_kpi(current_data, resi_standalone_current)
kpi_o = met.compute_channel_kpi(old_data, resi_standalone_old)
show_kpi_block("📊 KPI Principali — confronto anno precedente", kpi_c, kpi_o)

diretti_c = met.compute_channel_kpi(current_data, resi_standalone_current, diretto_pred)
diretti_o = met.compute_channel_kpi(old_data, resi_standalone_old, diretto_pred)
show_kpi_block("🟢 Diretti — fatturato e scostamento", diretti_c, diretti_o)

zalando_c = met.compute_channel_kpi(current_data, resi_standalone_current, zalando_pred)
zalando_o = met.compute_channel_kpi(old_data, resi_standalone_old, zalando_pred)
show_kpi_block("🟠 Zalando (ZFS) — fatturato e scostamento", zalando_c, zalando_o)

st.divider()
st.subheader("📅 Andamento Mensile — Fatturato Netto Reale")
trend = rb.monthly_trend(current_data, old_data, resi_standalone_current, resi_standalone_old, y_curr, y_old)
if trend.empty:
    st.caption("Nessuna vendita con data valida trovata nel periodo/perimetro selezionato.")
else:
    fig = px.line(trend, x="Mese", y=[f"Fatt.Netto Reale {y_curr}", f"Fatt.Netto Reale {y_old}"], markers=True)
    fig.update_layout(legend_title_text="", yaxis_title="Fatturato Netto Reale (€)")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(trend, hide_index=True, use_container_width=True, column_config={
        f"Fatt.Netto Reale {y_curr}": currency_col(), f"Fatt.Netto Reale {y_old}": currency_col(),
        "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
        f"Scontrino Medio {y_curr}": currency_col(),
    })

st.divider()
for title, key, sort_type in [
    ("📦 Dettaglio Marketplace (Y2Y)", "mkp", "fatturatoNetto"),
    ("🌍 Dettaglio Nazioni (Y2Y)", "nazione", "fatturatoNetto"),
    ("📈 Dettaglio Collezioni (Y2Y)", "clzMappata", "paiaNette"),
]:
    st.subheader(title)
    df = rb.comparative_table(agg.aggregate_by_key(current_data, key), agg.aggregate_by_key(old_data, key),
                               y_curr, y_old, sort_type)
    st.dataframe(df, hide_index=True, use_container_width=True, column_config={
        f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_old}": currency_col(),
        "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
        f"Paia Nette {y_curr}": number_col(), f"Paia Nette {y_old}": number_col(),
    })

st.divider()
st.subheader("🏆 Top 20 Articoli — Anno Corrente (con confronto Y2Y)")
top = rb.top_articoli_y2y(current_data, old_data, pipe.anagrafica, y_curr, y_old, top_n=20)
st.dataframe(top, hide_index=True, use_container_width=True, column_config={
    "Foto": image_col(), f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_old}": currency_col(),
    "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(), f"Paia Nette {y_curr}": number_col(),
})
