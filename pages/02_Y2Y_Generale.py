import plotly.express as px
import streamlit as st

from core import db, metrics as met
from core import aggregations as agg
from core import report_builders as rb
from core.design_system import page_setup, section, data_table, chart, empty_state
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels, shift_year

page_setup("Comparativa Year-over-Year", "📈",
           "Generale · confronto con anno−1 e anno−2 sul periodo scelto")

pipe = guard_pipeline()

if pipe.old_data.empty:
    empty_state("L'anno−1 non è coperto dal DB: non ci sono dati da confrontare. "
                "Scegli un periodo il cui anno precedente sia coperto in Carica Dati e rigenera.", "⚠️")
    st.stop()

y_curr, y_old = period_labels(2)
st.markdown(
    f"<p class='ds-caption'><b>{y_curr}</b>: {st.session_state.get('periodo_a_label', '—')} · "
    f"<b>{y_old}</b>: {st.session_state.get('periodo_b_label', '—')}</p>",
    unsafe_allow_html=True,
)

current_data, old_data = pipe.current_data, pipe.old_data
resi_standalone_current = pipe.esito_resi_current["standalone"]
resi_standalone_old = pipe.esito_resi_old["standalone"]

# --- Anno−2 opzionale (spunta "Confronta anche 2 anni precedenti" in Carica Dati):
# calcolato automaticamente spostando di due anni il periodo scelto in home.
periodo_a = st.session_state.get("sel_periodo_a")
mostra_3_vie = bool(periodo_a and st.session_state.get("sel_confronta_2anni", False))

y_2anni = None
data_2anni, standalone_2anni = current_data.iloc[0:0], resi_standalone_current.iloc[0:0]
if mostra_3_vie:
    periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
    conn = db.connect()
    data_2anni, standalone_2anni = db.query_period(conn, *periodo_c, pipe.perimetro)
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
        empty_state("Nessun dato rilevato nel periodo/perimetro selezionato.")
        return
    col_config = {"Var % Y2Y": percent_col(f"Var % vs {label_old}")}
    if kc2 is not None and label_2 is not None:
        block2 = rb.kpi_block(kc, kc2, label_curr, label_2)
        if block2 is not None:
            block[label_2] = block2[label_2]
            block[f"Var % vs {label_2}"] = block2["Var % Y2Y"]
            col_config[f"Var % vs {label_2}"] = percent_col()
    data_table(block, col_config)


kpi_c = met.compute_channel_kpi(current_data, resi_standalone_current)
kpi_o = met.compute_channel_kpi(old_data, resi_standalone_old)
kpi_2 = met.compute_channel_kpi(data_2anni, standalone_2anni) if mostra_3_vie else None
show_kpi_block("KPI principali", kpi_c, kpi_o, y_curr, y_old, kpi_2, y_2anni)

diretto_c = met.compute_channel_kpi(current_data, resi_standalone_current, diretto_pred)
diretto_o = met.compute_channel_kpi(old_data, resi_standalone_old, diretto_pred)
diretto_2 = met.compute_channel_kpi(data_2anni, standalone_2anni, diretto_pred) if mostra_3_vie else None
show_kpi_block("Diretti — fatturato e scostamento", diretto_c, diretto_o, y_curr, y_old, diretto_2, y_2anni)

zalando_c = met.compute_channel_kpi(current_data, resi_standalone_current, zalando_pred)
zalando_o = met.compute_channel_kpi(old_data, resi_standalone_old, zalando_pred)
zalando_2 = met.compute_channel_kpi(data_2anni, standalone_2anni, zalando_pred) if mostra_3_vie else None
show_kpi_block("Zalando (ZFS) — fatturato e scostamento", zalando_c, zalando_o, y_curr, y_old, zalando_2, y_2anni)

section("Andamento mensile — fatturato netto reale",
       caption="Mesi dal mese di inizio del periodo scelto al mese finale (finestra mobile, "
               "non fissa gennaio→dicembre): es. periodo 2025-11-01 → 2026-11-01 = "
               "novembre 2025 … novembre 2026. Ogni mese porta la propria stagione "
               "SS (mar→ago) / FW (set→feb) e le variazioni vs anno−1 (e anno−2 se attivo).")
periodo_sel = st.session_state.get("sel_periodo_a")
if periodo_sel:
    periodi_mensili = [(y_curr, current_data, resi_standalone_current),
                       (y_old, old_data, resi_standalone_old)]
    if mostra_3_vie and not data_2anni.empty:
        periodi_mensili.append((y_2anni, data_2anni, standalone_2anni))
    trend, stagioni = rb.monthly_season_report(periodo_sel[0], periodo_sel[1], periodi_mensili)
    if trend.empty:
        empty_state("Nessuna vendita con data valida trovata nel periodo/perimetro selezionato.")
    else:
        y_cols = [c for c in trend.columns if c.startswith("Fatturato Netto ")]
        fig = px.line(trend, x="Mese", y=y_cols, markers=True)
        fig.update_layout(legend_title_text="")
        chart(fig, y_title="Fatturato netto reale (€)")
        col_config = {}
        for c in trend.columns:
            if c.startswith("Fatturato Netto "):
                col_config[c] = currency_col()
            elif c.startswith("VAR%"):
                col_config[c] = percent_col()
            elif c.startswith("% Reso"):
                col_config[c] = percent_col()
            elif c.startswith(("Ordini ", "Paia Nette ")):
                col_config[c] = number_col()
        data_table(trend, col_config)

        section("Statistiche stagioni SS/FW",
               caption="SS = 01 marzo → 31 agosto · FW = 01 settembre → 28-29 febbraio. "
                       "\u201cMesi nel periodo\u201d = mesi della stagione presenti nel periodo scelto (su 6).")
        data_table(stagioni, col_config)
else:
    trend = rb.monthly_trend(current_data, old_data, resi_standalone_current, resi_standalone_old, y_curr, y_old)
    if trend.empty:
        empty_state("Nessuna vendita con data valida trovata nel periodo/perimetro selezionato.")
    else:
        y_cols = [f"Fatt.Netto Reale {y_curr}", f"Fatt.Netto Reale {y_old}"]
        if mostra_3_vie and not data_2anni.empty:
            trend_2 = rb.monthly_trend(current_data, data_2anni, resi_standalone_current, standalone_2anni, y_curr, y_2anni)
            trend[f"Fatt.Netto Reale {y_2anni}"] = trend_2[f"Fatt.Netto Reale {y_2anni}"]
            y_cols.append(f"Fatt.Netto Reale {y_2anni}")
        fig = px.line(trend, x="Mese", y=y_cols, markers=True)
        fig.update_layout(legend_title_text="")
        chart(fig, y_title="Fatturato netto reale (€)")
        col_config = {c: currency_col() for c in y_cols}
        col_config.update({"VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
                            f"Scontrino Medio {y_curr}": currency_col()})
        data_table(trend, col_config)

st.divider()
for title, key, sort_type in [
    ("Dettaglio Marketplace (Y2Y)", "mkp", "fatturatoNetto"),
    ("Dettaglio Nazioni (Y2Y)", "nazione", "fatturatoNetto"),
    ("Dettaglio Collezioni (Y2Y)", "clzMappata", "paiaNette"),
]:
    section(title)
    df = rb.comparative_table(agg.aggregate_by_key(current_data, key), agg.aggregate_by_key(old_data, key),
                               y_curr, y_old, sort_type)
    data_table(df, {
        f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_old}": currency_col(),
        "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
        f"Paia Nette {y_curr}": number_col(), f"Paia Nette {y_old}": number_col(),
    })
    if mostra_3_vie and not data_2anni.empty:
        with st.expander(f"Confronto con {y_2anni}"):
            df2 = rb.comparative_table(agg.aggregate_by_key(current_data, key), agg.aggregate_by_key(data_2anni, key),
                                        y_curr, y_2anni, sort_type)
            data_table(df2, {
                f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_2anni}": currency_col(),
                "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(),
                f"Paia Nette {y_curr}": number_col(), f"Paia Nette {y_2anni}": number_col(),
            })

section(f"Top 20 articoli — {y_curr}",
       caption="Classifica per fatturato netto reale, con confronto Y2Y e foto articolo.")
top = rb.top_articoli_y2y(current_data, old_data, pipe.anagrafica, y_curr, y_old, top_n=20)
data_table(top, {
    "Foto": image_col(), f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_old}": currency_col(),
    "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(), f"Paia Nette {y_curr}": number_col(),
})
if mostra_3_vie and not data_2anni.empty:
    with st.expander(f"Top 20 articoli — confronto con {y_2anni}"):
        top2 = rb.top_articoli_y2y(current_data, data_2anni, pipe.anagrafica, y_curr, y_2anni, top_n=20)
        data_table(top2, {
            "Foto": image_col(), f"Fatt.Netto {y_curr}": currency_col(), f"Fatt.Netto {y_2anni}": currency_col(),
            "VAR% FATT": percent_col(), f"% Reso {y_curr}": percent_col(), f"Paia Nette {y_curr}": number_col(),
        })
