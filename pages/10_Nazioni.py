import streamlit as st

from core import report_builders as rb
from core import db
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, period_labels, shift_year

st.set_page_config(page_title="Nazioni", page_icon="🌍", layout="wide")
st.title("🌍 Comparativa Nazioni")

pipe = guard_pipeline()

y_curr, y_old = period_labels(2)
ha_confronto = not pipe.old_data.empty
st.caption(
    f"**{y_curr}**: {st.session_state.get('periodo_a_label', '—')}"
    + (f" · **{y_old}**: {st.session_state.get('periodo_b_label', '—')}" if ha_confronto else "")
)

current_data = pipe.current_data
old_data = pipe.old_data
standalone_current = pipe.esito_resi_current["standalone"]
standalone_old = pipe.esito_resi_old["standalone"]

mostra_3_anno = False
periodo_a = st.session_state.get("sel_periodo_a")
y_2anni = None
data_2anni, standalone_2anni = current_data.iloc[0:0], standalone_current.iloc[0:0]
periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
conn = db.connect()
data_2anni, standalone_2anni = db.query_period(conn, *periodo_c, pipe.perimetro)
y_2anni = period_labels(3)[2]
if not data_2anni.empty:
    mostra_3_anno = True

st.caption(f"**{y_2anni}**: {periodo_c[0]} → {periodo_c[1]}")
if data_2anni.empty:
    st.caption("Nessun dato nel DB per 'due anni precedenti': il confronto a 3 vie resterà vuoto.")

opzioni_nazioni = rb.nazioni_disponibili(current_data, old_data)
if not opzioni_nazioni:
    st.caption("Nessuna nazione trovata nel periodo selezionato.")
    st.stop()

opzioni_nazioni.insert(0, "GLOBAL")
nazioni_scelte = st.multiselect("Nazioni da comparare", opzioni_nazioni, default=["GLOBAL","IT","DE","FR","GB","US"])
if not nazioni_scelte:
    st.info("Seleziona almeno una nazione.")
    st.stop()

st.divider()
st.subheader(f"📊 KPI per nazione — {y_curr}")
tabella_curr = rb.nazioni_metrics(current_data, standalone_current, nazioni_scelte)
st.dataframe(tabella_curr, hide_index=True, use_container_width=True, column_config={
    "Fatturato Netto Totale": currency_col(),
    "% Reso": percent_col(),
    "Totale Ordini": number_col(), "Totale Paia Nette": number_col(),
    "Paia Rese (spedito nel range)": number_col(), "Paia Rese (spedito fuori range)": number_col(),
})

if ha_confronto:
    st.subheader(f"📊 KPI per nazione — {y_old}")
    tabella_old = rb.nazioni_metrics(old_data, standalone_old, nazioni_scelte)
    st.dataframe(tabella_old, hide_index=True, use_container_width=True, column_config={
        "Fatturato Netto Totale": currency_col(),
        "% Reso": percent_col(),
        "Totale Ordini": number_col(), "Totale Paia Nette": number_col(),
        "Paia Rese (spedito nel range)": number_col(), "Paia Rese (spedito fuori range)": number_col(),
    })

    st.subheader("📈 Variazione % fatturato netto totale")
    merge = tabella_curr[["Nazione", "Fatturato Netto Totale"]].merge(
        tabella_old[["Nazione", "Fatturato Netto Totale"]], on="Nazione", suffixes=(f" {y_curr}", f" {y_old}"))
    merge["VAR%"] = merge.apply(
        lambda r: rb.var_pct(r[f"Fatturato Netto Totale {y_curr}"], r[f"Fatturato Netto Totale {y_old}"]), axis=1)
    st.dataframe(merge, hide_index=True, use_container_width=True, column_config={
        f"Fatturato Netto Totale {y_curr}": currency_col(), f"Fatturato Netto Totale {y_old}": currency_col(),
        "VAR%": percent_col(),
    })

st.divider()
st.subheader("🏷️ Share del fatturato per brand, per nazione")
tabs = st.tabs(nazioni_scelte)
for tab, naz in zip(tabs, nazioni_scelte):
    with tab:
        #col1, col2 = st.columns(2) if ha_confronto else (st.container(), None)
        st.caption(y_curr)
        share_curr = rb.nazioni_brand_share(current_data, naz)
        st.dataframe(share_curr, hide_index=True, use_container_width=True, column_config={
            "Fatturato Netto": currency_col(),
            "Ordini": number_col(),
            "Share %": percent_col(),
            "Paia spedite": number_col(),
            "Paia rese": number_col(),
            "Paia nette": number_col(),
            "% Reso": percent_col(),
            "Scontrino Medio": currency_col(),
        })
        if ha_confronto:
            st.caption(y_old)
            share_old = rb.nazioni_brand_share(old_data, naz)
            st.dataframe(share_old, hide_index=True, use_container_width=True, column_config={
                "Fatturato Netto": currency_col(),
                "Ordini": number_col(),
                "Share %": percent_col(),
                "Paia spedite": number_col(),
                "Paia rese": number_col(),
                "Paia nette": number_col(),
                "% Reso": percent_col(),
                "Scontrino Medio": currency_col(),
            })
        if mostra_3_anno:
            st.caption(y_2anni)
            share_old2 = rb.nazioni_brand_share(data_2anni, naz)
            st.dataframe(share_old2, hide_index=True, use_container_width=True, column_config={
                "Fatturato Netto": currency_col(),
                "Ordini": number_col(),
                "Share %": percent_col(),
                "Paia spedite": number_col(),
                "Paia rese": number_col(),
                "Paia nette": number_col(),
                "% Reso": percent_col(),
                "Scontrino Medio": currency_col(),
            })import streamlit as st

from core import report_builders as rb
from core import db
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, period_labels, shift_year

st.set_page_config(page_title="Nazioni", page_icon="🌍", layout="wide")
st.title("🌍 Comparativa Nazioni")

pipe = guard_pipeline()

y_curr, y_old = period_labels(2)
ha_confronto = not pipe.old_data.empty
st.caption(
    f"**{y_curr}**: {st.session_state.get('periodo_a_label', '—')}"
    + (f" · **{y_old}**: {st.session_state.get('periodo_b_label', '—')}" if ha_confronto else "")
)

current_data = pipe.current_data
old_data = pipe.old_data
standalone_current = pipe.esito_resi_current["standalone"]
standalone_old = pipe.esito_resi_old["standalone"]

mostra_3_anno = False
periodo_a = st.session_state.get("sel_periodo_a")
y_2anni = None
data_2anni, standalone_2anni = current_data.iloc[0:0], standalone_current.iloc[0:0]
periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
conn = db.connect()
data_2anni, standalone_2anni = db.query_period(conn, *periodo_c, pipe.perimetro)
y_2anni = period_labels(3)[2]
if not data_2anni.empty:
    mostra_3_anno = True

st.caption(f"**{y_2anni}**: {periodo_c[0]} → {periodo_c[1]}")
if data_2anni.empty:
    st.caption("Nessun dato nel DB per 'due anni precedenti': il confronto a 3 vie resterà vuoto.")

opzioni_nazioni = rb.nazioni_disponibili(current_data, old_data)
if not opzioni_nazioni:
    st.caption("Nessuna nazione trovata nel periodo selezionato.")
    st.stop()

opzioni_nazioni.insert(0, "GLOBAL")
nazioni_scelte = st.multiselect("Nazioni da comparare", opzioni_nazioni, default=["GLOBAL","IT","DE","FR","GB","US"])
if not nazioni_scelte:
    st.info("Seleziona almeno una nazione.")
    st.stop()

st.divider()
st.subheader(f"📊 KPI per nazione — {y_curr}")
tabella_curr = rb.nazioni_metrics(current_data, standalone_current, nazioni_scelte)
st.dataframe(tabella_curr, hide_index=True, use_container_width=True, column_config={
    "Fatturato Netto Totale": currency_col(),
    "% Reso": percent_col(),
    "Totale Ordini": number_col(), "Totale Paia Nette": number_col(),
    "Paia Rese (spedito nel range)": number_col(), "Paia Rese (spedito fuori range)": number_col(),
})

if ha_confronto:
    st.subheader(f"📊 KPI per nazione — {y_old}")
    tabella_old = rb.nazioni_metrics(old_data, standalone_old, nazioni_scelte)
    st.dataframe(tabella_old, hide_index=True, use_container_width=True, column_config={
        "Fatturato Netto Totale": currency_col(),
        "% Reso": percent_col(),
        "Totale Ordini": number_col(), "Totale Paia Nette": number_col(),
        "Paia Rese (spedito nel range)": number_col(), "Paia Rese (spedito fuori range)": number_col(),
    })

    st.subheader("📈 Variazione % fatturato netto totale")
    merge = tabella_curr[["Nazione", "Fatturato Netto Totale"]].merge(
        tabella_old[["Nazione", "Fatturato Netto Totale"]], on="Nazione", suffixes=(f" {y_curr}", f" {y_old}"))
    merge["VAR%"] = merge.apply(
        lambda r: rb.var_pct(r[f"Fatturato Netto Totale {y_curr}"], r[f"Fatturato Netto Totale {y_old}"]), axis=1)
    st.dataframe(merge, hide_index=True, use_container_width=True, column_config={
        f"Fatturato Netto Totale {y_curr}": currency_col(), f"Fatturato Netto Totale {y_old}": currency_col(),
        "VAR%": percent_col(),
    })

st.divider()
st.subheader("🏷️ Share del fatturato per brand, per nazione")
tabs = st.tabs(nazioni_scelte)
for tab, naz in zip(tabs, nazioni_scelte):
    with tab:
        #col1, col2 = st.columns(2) if ha_confronto else (st.container(), None)
        st.caption(y_curr)
        share_curr = rb.nazioni_brand_share(current_data, naz)
        st.dataframe(share_curr, hide_index=True, use_container_width=True, column_config={
            "Fatturato Netto": currency_col(),
            "Ordini": number_col(),
            "Share %": percent_col(),
            "Paia spedite": number_col(),
            "Paia rese": number_col(),
            "Paia nette": number_col(),
            "% Reso": percent_col(),
            "Scontrino Medio": currency_col(),
        })
        if ha_confronto:
            st.caption(y_old)
            share_old = rb.nazioni_brand_share(old_data, naz)
            st.dataframe(share_old, hide_index=True, use_container_width=True, column_config={
                "Fatturato Netto": currency_col(),
                "Ordini": number_col(),
                "Share %": percent_col(),
                "Paia spedite": number_col(),
                "Paia rese": number_col(),
                "Paia nette": number_col(),
                "% Reso": percent_col(),
                "Scontrino Medio": currency_col(),
            })
        if mostra_3_anno:
            st.caption(y_2anni)
            share_old2 = rb.nazioni_brand_share(data_2anni, naz)
            st.dataframe(share_old2, hide_index=True, use_container_width=True, column_config={
                "Fatturato Netto": currency_col(),
                "Ordini": number_col(),
                "Share %": percent_col(),
                "Paia spedite": number_col(),
                "Paia rese": number_col(),
                "Paia nette": number_col(),
                "% Reso": percent_col(),
                "Scontrino Medio": currency_col(),
            })

st.divider()
st.subheader("📊 Report unificato 3 anni — Marketplace × Nazione × Brand")
st.caption(
    "Un report per ciascun anno di confronto con righe aggregate per scope: "
    "DETAIL, MARKETPLACE_COUNTRY, MARKETPLACE_BRAND, COUNTRY_BRAND, GLOBAL_MARKETPLACE, "
    "GLOBAL_COUNTRY, GLOBAL_BRAND, GLOBAL. Le nazioni di dettaglio seguono il selettore "
    "'Nazioni da comparare'; le righe GLOBAL sono sempre presenti. "
    "Share % = peso sul fatturato GLOBAL dello stesso anno. "
    "Var % YoY = confronto con l'anno precedente della stessa combinazione (vuota se "
    "l'anno prima non esisteva). Reso % (valore) = netto reso / netto spedito. "
    "Nota: il report usa solo dati venduto, quindi NON include i resi con spedizione "
    "fuori range (standalone) che invece entrano nella tabella KPI per nazione: i totali "
    "delle due tabelle differiscono per costruzione."
)
periodi_report = [(y_curr, current_data)]
if ha_confronto:
    periodi_report.append((y_old, old_data))
if mostra_3_anno:
    periodi_report.append((y_2anni, data_2anni))
unificata = rb.nazioni_unified_report(periodi_report, nazioni_scelte)
if unificata.empty:
    st.caption("Nessun dato disponibile per il report unificato.")
else:
    cfg_unificata = {
        "Fatturato Netto": currency_col(),
        "Share %": percent_col(),
        "Scontrino Medio": currency_col(),
        "Ordini": number_col(),
        "Paia spedite": number_col(),
        "Paia rese": number_col(),
        "Paia nette": number_col(),
        "Reso %": percent_col(),
        "Reso % (valore)": percent_col(),
        "Var % Fatturato YoY": percent_col(),
        "Var % Ordini YoY": percent_col(),
        "Margine Lordo": currency_col(),
        "Margine %": percent_col(),
    }
    cfg_unificata = {k: v for k, v in cfg_unificata.items() if k in unificata.columns}
    st.dataframe(unificata, hide_index=True, use_container_width=True, column_config=cfg_unificata)
    st.download_button(
        "⬇️ Scarica il report unificato (CSV)",
        data=unificata.to_csv(index=False).encode("utf-8-sig"),
        file_name="report_unificato_nazioni.csv",
        mime="text/csv",
    )
