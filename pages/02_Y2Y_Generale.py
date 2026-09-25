import plotly.express as px
import streamlit as st

from core import db, metrics as met
from core import aggregations as agg
from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels, shift_year

st.set_page_config(page_title="Y2Y Generale", page_icon="📈", layout="wide")
st.title("📈 Comparativa Year-over-Year — Generale")

pipe = guard_pipeline()

if pipe.old_data.empty:
    st.warning("Scegli anche un periodo di confronto in home per abilitare i confronti Y2Y.")
    st.stop()

y_curr, y_old = period_labels(2)
st.caption(
    f"**{y_curr}**: {st.session_state.get('periodo_a_label', '—')} · "
    f"**{y_old}**: {st.session_state.get('periodo_b_label', '—')}"
)

current_data, old_data = pipe.current_data, pipe.old_data
resi_standalone_current = pipe.esito_resi_current["standalone"]
resi_standalone_old = pipe.esito_resi_old["standalone"]

# --- Confronto opzionale a 3 vie (solo su questa pagina): "due anni precedenti", calcolato
# automaticamente spostando di un altro anno il periodo scelto in home — non richiede una
# terza selezione di date, per non appesantire la home per gli altri report che restano a 2.
periodo_a = st.session_state.get("sel_periodo_a")
mostra_3_vie = False
if periodo_a and isinstance(periodo_a, tuple) and len(periodo_a) == 2:
    mostra_3_vie = st.checkbox("Aggiungi confronto con 'Due anni precedenti' (calcolato automaticamente)",
                                value=False)

y_2anni = None
data_2anni, standalone_2anni = current_data.iloc[0:0], resi_standalone_current.iloc[0:0]
if mostra_3_vie:
    periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
    conn = db.connect()
    data_2anni, standalone_2anni = db.query_period(conn, *periodo_c, pipe.perimetro)
    y_2anni = period_labels(3)[2]
    st.caption(f"**{y_2anni}**: {periodo_c[0]} → {periodo_c[1]}")
    if data_2anni.empty:
        st.caption("Nessun dato nel DB per 'due anni precedenti': il confronto a 3 vie resterà vuoto.")

diretto_pred = lambda df: df["tipoSpedizione"] == "DIRETTO"
zalando_pred = lambda df: df["ordineId"].str.contains("_ZFS", na=False) if not df.empty else df.index < 0


def show_kpi_block(title, kc, ko, label_curr, label_old, kc2=None, label_2=None):
    st.subheader(title)
    block = rb.kpi_block(kc, ko, label_curr, label_old)
    if block is None:
        st.caption("Nessun dato rilevato nel periodo/perimetro selezionato.")
        return
    col_config = {"Var % Y2Y": percent_col(f"Var % vs {label_old}")}
    if kc2 is not None and label_2 is not None:
        block2 = rb.kpi_block(kc, kc2, label_curr, label_2)
        if block2 is not None:
            block[label_2] = block2[label_2]
            block[f"Var % vs {label_2}"] = block2["Var % Y2Y"]
            col_config[f"Var % vs {label_2}"] = percent_col()
    st.dataframe(block, hide_index=True, use_container_width=True, column_config=col_config)


kpi_c = met.compute_channel_kpi(current_data, resi_standalone_current)
kpi_o = met.compute_channel_kpi(old_data, resi_standalone_old)
kpi_2 = met.compute_channel_kpi(data_2anni, standalone_2anni) if mostra_3_vie else None
show_kpi_block("📊 KPI Principali", kpi_c, kpi_o, y_curr, y_old, kpi_2, y_2anni)

diretto_c = met.compute_channel_kpi(current_data, resi_standalone_current, diretto_pred)
diretto_o = met.compute_channel_kpi(old_data, resi_standalone_old, diretto_pred)
diretto_2 = met.compute_channel_kpi(data_2anni, standalone_2anni, diretto_pred) if mostra_3_vie else None
show_kpi_block("🟢 Diretti — fatturato e scostamento", diretto_c, diretto_o, y_curr, y_old, diretto_2, y_2anni)

zalando_c = met.compute_channel_kpi(current_data, resi_standalone_current, zalando_pred)
zalando_o = met.compute_channel_kpi(old_data, resi_standalone_old, zalando_pred)
zalando_2 = met.compute_channel_kpi(data_2anni, standalone_2anni, zalando_pred) if mostra_3_vie else None
show_kpi_block("🟠 Zalando (ZFS) — fatturato e scostamento", zalando_c, zalando_o, y_curr, y_old, zalando_2, y_2anni)

st.divider()
st.subheader("📅 Andamento Mensile — Fatturato Netto Reale")
trend = rb.monthly_trend(current_data, old_data, resi_standalone_current, resi_standalone_old, y_curr, y_old)
if trend.empty:
    st.caption("Nessuna vendita con data valida trovata nel periodo/perimetro selezionato.")
else:
    y_cols = [f"Fatt.Netto Reale {y_curr}", f"Fatt.Netto Reale {y_old}"]
    if mostra_3_vie and not data_2anni.empty:
        trend_2 = rb.monthly_trend(current_data, data_2anni, resi_standalone_current, standalone_2anni, y_curr, y_2anni)
        trend[f"Fatt.Netto Reale {y_2anni}"] = trend_2[f"Fatt.Netto Reale {y_2anni}"]
        y_cols.append(f"Fatt.Netto Reale {y_2anni}")
    fig = px.line(trend, x="Mese", y=y_cols, markers=True)
    fig.update_layout(legend_title_text="", yaxis_title="Fatturato Netto Reale (€)")
    st.plotly_chart(fig, use_container_width=True)
    col_config = {c: currency_col() for c in y_cols}
    col_config.update({"VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
                        f"Scontrino Medio {y_curr}": currency_col()})
    st.dataframe(trend, hide_index=True, use_container_width=True, column_config=col_config)

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
    if mostra_3_vie and not data_2anni.empty:
        with st.expander(f"Confronto con {y_2anni}"):
            df2 = rb.comparative_table(agg.aggregate_by_key(current_data, key), agg.aggregate_by_key(data_2anni, key),
                                        y_curr, y_2anni, sort_type)
            st.dataframe(df2, hide_index=True, use_container_width=True, column_config={
                f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_2anni}": currency_col(),
                "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
                f"Paia Nette {y_curr}": number_col(), f"Paia Nette {y_2anni}": number_col(),
            })

st.divider()
st.subheader(f"🏆 Top 20 Articoli — {y_curr} (con confronto Y2Y)")
top = rb.top_articoli_y2y(current_data, old_data, pipe.anagrafica, y_curr, y_old, top_n=20)
st.dataframe(top, hide_index=True, use_container_width=True, column_config={
    "Foto": image_col(), f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_old}": currency_col(),
    "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(), f"Paia Nette {y_curr}": number_col(),
})
if mostra_3_vie and not data_2anni.empty:
    with st.expander(f"Top 20 Articoli — confronto con {y_2anni}"):
        top2 = rb.top_articoli_y2y(current_data, data_2anni, pipe.anagrafica, y_curr, y_2anni, top_n=20)
        st.dataframe(top2, hide_index=True, use_container_width=True, column_config={
            "Foto": image_col(), f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_2anni}": currency_col(),
            "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(), f"Paia Nette {y_curr}": number_col(),
        })
