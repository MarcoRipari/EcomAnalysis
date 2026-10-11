import streamlit as st

from core import db
from core import report_builders as rb
from core.design_system import page_setup, section, data_table, empty_state
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, period_labels, shift_year

page_setup("Nazioni & Geografia", "🌍",
           "Fatturato, paia e resi per nazione, con la ripartizione per brand")

pipe = guard_pipeline()

y_curr, y_old = period_labels(2)
ha_confronto = not pipe.old_data.empty
st.markdown(
    f"<p class='ds-caption'><b>{y_curr}</b>: {st.session_state.get('periodo_a_label', '—')}"
    + (f" · <b>{y_old}</b>: {st.session_state.get('periodo_b_label', '—')}" if ha_confronto else "")
    + "</p>",
    unsafe_allow_html=True,
)

# periodi in confronto: (etichetta, venduto, resi fuori periodo)
periodi = [(y_curr, pipe.current_data, pipe.resi_fp_current)]
if ha_confronto:
    periodi.append((y_old, pipe.old_data, pipe.resi_fp_old))

periodo_a = st.session_state.get("sel_periodo_a")
if periodo_a and st.session_state.get("sel_confronta_2anni", False):
    periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
    data_2, resi_fp_2 = db.query_period(db.connect(), *periodo_c, pipe.perimetro)
    y_2anni = period_labels(3)[2]
    st.markdown(f"<p class='ds-caption'><b>{y_2anni}</b>: {periodo_c[0]} → {periodo_c[1]}</p>",
                unsafe_allow_html=True)
    if data_2.empty and resi_fp_2.empty:
        st.caption("Nessun dato nel DB per l'anno−2: il confronto resterà vuoto.")
    else:
        periodi.append((y_2anni, data_2, resi_fp_2))

opzioni = rb.nazioni_disponibili(*[d for _, v, r in periodi for d in (v, r)])
if not opzioni:
    empty_state("Nessuna nazione trovata nel periodo selezionato.")
    st.stop()

nazioni_scelte = st.multiselect(
    "Nazioni da comparare", ["GLOBAL"] + opzioni,
    default=[n for n in ["GLOBAL", "IT", "DE", "FR", "GB", "US"] if n == "GLOBAL" or n in opzioni])
if not nazioni_scelte:
    st.info("Seleziona almeno una nazione.")
    st.stop()

CONF_KPI = {
    "Fatturato": currency_col(), "% Reso": percent_col(), "Paia Nette": number_col(),
    "Paia Rese (vendite del periodo)": number_col(), "Paia Rese (vendite fuori periodo)": number_col(),
}
CONF_BRAND = {
    "Fatturato": currency_col(), "Share %": percent_col(), "Valore Medio Paio": currency_col(),
    "Paia spedite": number_col(), "Paia rese": number_col(), "Paia nette": number_col(),
    "% Reso": percent_col(),
}

section("KPI per nazione")
tabelle = {}
for label, venduto, resi_fp in periodi:
    tabelle[label] = rb.nazioni_metrics(venduto, resi_fp, nazioni_scelte)
    st.caption(label)
    data_table(tabelle[label], CONF_KPI)

if ha_confronto:
    section("Variazione % del Fatturato")
    merge = tabelle[y_curr][["Nazione", "Fatturato"]].merge(
        tabelle[y_old][["Nazione", "Fatturato"]], on="Nazione", suffixes=(f" {y_curr}", f" {y_old}"))
    merge["VAR%"] = merge.apply(
        lambda r: rb.var_pct(r[f"Fatturato {y_curr}"], r[f"Fatturato {y_old}"]), axis=1)
    data_table(merge, {f"Fatturato {y_curr}": currency_col(),
                       f"Fatturato {y_old}": currency_col(), "VAR%": percent_col()})

section("Ripartizione del Fatturato per brand")
for tab, naz in zip(st.tabs(nazioni_scelte), nazioni_scelte):
    with tab:
        for label, venduto, resi_fp in periodi:
            st.caption(label)
            data_table(rb.nazioni_brand_share(venduto, naz, resi_fp), CONF_BRAND)
