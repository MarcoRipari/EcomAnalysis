import plotly.express as px
import streamlit as st

from core import db, metrics as met
from core import aggregations as agg
from core import report_builders as rb
from core.design_system import page_setup, section, data_table, chart, empty_state
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels, shift_year

page_setup("Comparativa Year-over-Year", None)

pipe = guard_pipeline()

if pipe.old_data.empty:
    empty_state("Dati del periodo di confronto non disponibili.")
    st.stop()

y_curr, y_old = period_labels(2)
st.markdown(
    f"<p class='ds-caption'><b>{y_curr}</b>: {st.session_state.get('periodo_a_label', '—')} · "
    f"<b>{y_old}</b>: {st.session_state.get('periodo_b_label', '—')}</p>",
    unsafe_allow_html=True,
)

current_data, old_data = pipe.current_data, pipe.old_data
resi_fp_current = pipe.resi_fp_current
resi_fp_old = pipe.resi_fp_old

# --- Anno−2 opzionale (spunta "Confronta anche 2 anni precedenti" in Carica Dati):
# calcolato automaticamente spostando di due anni il periodo scelto in home.
periodo_a = st.session_state.get("sel_periodo_a")
mostra_3_vie = bool(periodo_a and st.session_state.get("sel_confronta_2anni", False))

y_2anni = None
data_2anni, resi_fp_2anni = current_data.iloc[0:0], resi_fp_current.iloc[0:0]
if mostra_3_vie:
    periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
    conn = db.connect()
    data_2anni, resi_fp_2anni = db.query_period(conn, *periodo_c, pipe.perimetro)
    y_2anni = period_labels(3)[2]
    st.markdown(f"<p class='ds-caption'><b>{y_2anni}</b>: {periodo_c[0]} → {periodo_c[1]}</p>",
                unsafe_allow_html=True)
    if data_2anni.empty:
        st.markdown("<p class='ds-caption'>Nessun dato nel DB per l'anno−2: il confronto resterà vuoto.</p>",
                    unsafe_allow_html=True)

diretto_pred = lambda df: df["tipoSpedizione"] == "DIRETTO"
zalando_pred = lambda df: df["ordineId"].str.contains("_ZFS", na=False) if not df.empty else df.index < 0


def show_kpi_block(title, kc, ko, label_curr, label_old, kc2=None, label_2=None):
    section(title)
    block = rb.kpi_block(kc, ko, label_curr, label_old)
    if block is None:
        empty_state("Nessun dato rilevato nel periodo selezionato.")
        return
    col_config = {"Var % Y2Y": st.column_config.TextColumn(f"Var vs {label_old}")}
    if kc2 is not None and label_2 is not None:
        block2 = rb.kpi_block(kc, kc2, label_curr, label_2)
        if block2 is not None:
            block[label_2] = block2[label_2]
            block[f"Var % vs {label_2}"] = block2["Var % Y2Y"]
            col_config[f"Var % vs {label_2}"] = st.column_config.TextColumn(f"Var vs {label_2}")
    data_table(block, col_config)


kpi_c = met.compute_channel_kpi(current_data, resi_fp_current)
kpi_o = met.compute_channel_kpi(old_data, resi_fp_old)
kpi_2 = met.compute_channel_kpi(data_2anni, resi_fp_2anni) if mostra_3_vie else None
show_kpi_block("KPI Principali", kpi_c, kpi_o, y_curr, y_old, kpi_2, y_2anni)

diretto_c = met.compute_channel_kpi(current_data, resi_fp_current, diretto_pred)
diretto_o = met.compute_channel_kpi(old_data, resi_fp_old, diretto_pred)
diretto_2 = met.compute_channel_kpi(data_2anni, resi_fp_2anni, diretto_pred) if mostra_3_vie else None
show_kpi_block("Canale Diretti", diretto_c, diretto_o, y_curr, y_old, diretto_2, y_2anni)

zalando_c = met.compute_channel_kpi(current_data, resi_fp_current, zalando_pred)
zalando_o = met.compute_channel_kpi(old_data, resi_fp_old, zalando_pred)
zalando_2 = met.compute_channel_kpi(data_2anni, resi_fp_2anni, zalando_pred) if mostra_3_vie else None
show_kpi_block("Zalando (ZFS)", zalando_c, zalando_o, y_curr, y_old, zalando_2, y_2anni)

section("Andamento Mensile")
periodo_sel = st.session_state["sel_periodo_a"]
periodi_mensili = [(y_curr, current_data, resi_fp_current),
                   (y_old, old_data, resi_fp_old)]
if mostra_3_vie and not data_2anni.empty:
    periodi_mensili.append((y_2anni, data_2anni, resi_fp_2anni))
trend, stagioni = rb.monthly_season_report(periodo_sel[0], periodo_sel[1], periodi_mensili)
if trend.empty:
    empty_state("Nessuna vendita con data valida trovata nel periodo selezionato.")
else:
    brevi = [y_curr, y_old] + ([y_2anni] if y_2anni else [])
    lunghe = period_labels(3, lunghe=True)
    trend_grafico = trend.rename(columns={f"Fatturato {b}": f"Fatturato {l}" for b, l in zip(brevi, lunghe)})
    y_cols = [c for c in trend_grafico.columns if c.startswith("Fatturato ")]
    fig = px.line(trend_grafico, x="Mese", y=y_cols, markers=True)
    fig.update_layout(legend_title_text="")
    chart(fig, y_title="Fatturato (€)")
    col_config = {}
    for c in trend.columns:
        if c.startswith("Fatturato "):
            col_config[c] = currency_col()
        elif c.startswith("VAR%"):
            col_config[c] = percent_col()
        elif c.startswith("% Reso"):
            col_config[c] = percent_col()
        elif c.startswith("Paia Nette "):
            col_config[c] = number_col()
        elif c.startswith("Scontrino Medio"):
            col_config[c] = currency_col()
    data_table(trend, col_config)

    section("Stagioni SS/FW")
    data_table(stagioni, col_config)


st.divider()
for title, key, sort_type in [
    ("Dettaglio Marketplace (Y2Y)", "mkp", "fatturatoNetto"),
    ("Dettaglio Nazioni (Y2Y)", "nazione", "fatturatoNetto"),
    ("Dettaglio Collezioni (Y2Y)", "clzMappata", "paiaNette"),
]:
    section(title)
    df = rb.comparative_table(
        agg.aggregate_by_key(current_data, key, resi_fp_current),
        agg.aggregate_by_key(old_data, key, resi_fp_old),
        y_curr, y_old, sort_type
    )
    data_table(df, {
        f"Fatturato {y_curr}": currency_col(), f"Fatturato {y_old}": currency_col(),
        "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
        f"Paia Nette {y_curr}": number_col(), f"Paia Nette {y_old}": number_col(),
        f"Scontrino Medio {y_curr}": currency_col(), f"Scontrino Medio {y_old}": currency_col(),
    })
    if mostra_3_vie and not data_2anni.empty:
        with st.expander(f"Confronto con {y_2anni}"):
            df2 = rb.comparative_table(
                agg.aggregate_by_key(current_data, key, resi_fp_current),
                agg.aggregate_by_key(data_2anni, key, resi_fp_2anni),
                y_curr, y_2anni, sort_type
            )
            data_table(df2, {
                f"Fatturato {y_curr}": currency_col(), f"Fatturato {y_2anni}": currency_col(),
                "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
                f"Paia Nette {y_curr}": number_col(), f"Paia Nette {y_2anni}": number_col(),
                f"Scontrino Medio {y_curr}": currency_col(), f"Scontrino Medio {y_2anni}": currency_col(),
            })

section(f"Top 20 Articoli — {y_curr}")
top = rb.top_articoli_y2y(current_data, old_data, pipe.anagrafica, y_curr, y_old, top_n=20,
                          resi_fp_current=resi_fp_current, resi_fp_old=resi_fp_old)
data_table(top, {
    "Foto": image_col(), f"Fatturato {y_curr}": currency_col(), f"Fatturato {y_old}": currency_col(),
    "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(), f"Paia Nette {y_curr}": number_col(),
})
if mostra_3_vie and not data_2anni.empty:
    with st.expander(f"Top 20 articoli — confronto con {y_2anni}"):
        top2 = rb.top_articoli_y2y(current_data, data_2anni, pipe.anagrafica, y_curr, y_2anni, top_n=20,
                                   resi_fp_current=resi_fp_current, resi_fp_old=resi_fp_2anni)
        data_table(top2, {
            "Foto": image_col(), f"Fatturato {y_curr}": currency_col(), f"Fatturato {y_2anni}": currency_col(),
            "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(), f"Paia Nette {y_curr}": number_col(),
        })
