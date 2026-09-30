import streamlit as st

from core import report_builders as rb
from core import db
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, period_labels, shift_year

st.set_page_config(page_title="Report Unificato", page_icon="🧾", layout="wide")
st.title("🧾 Report unificato 3 anni — Marketplace × Nazione × Brand")
st.caption(
    "Un report per ciascun anno di confronto (Range selezionato, Anno precedente, Due anni "
    "precedenti) con righe aggregate per scope: DETAIL, MARKETPLACE_COUNTRY, MARKETPLACE_BRAND, "
    "COUNTRY_BRAND, GLOBAL_MARKETPLACE, GLOBAL_COUNTRY, GLOBAL_BRAND, GLOBAL. "
    "Tutte le nazioni presenti nei dati sono incluse automaticamente; le righe GLOBAL sono "
    "sempre presenti. Share % = peso sul fatturato GLOBAL dello stesso anno. "
    "Var % YoY = confronto con l'anno precedente della stessa combinazione (vuota se l'anno "
    "prima non esisteva). Reso % (valore) = netto reso / netto spedito. "
    "Nota: il report usa solo dati venduto, quindi NON include i resi con spedizione fuori "
    "range (standalone) che invece entrano nel Fatturato Netto Totale della pagina Nazioni: "
    "i totali delle due pagine differiscono per costruzione."
)

pipe = guard_pipeline()

y_curr, y_old = period_labels(2)
ha_confronto = not pipe.old_data.empty
st.caption(
    f"**{y_curr}**: {st.session_state.get('periodo_a_label', '—')}"
    + (f" · **{y_old}**: {st.session_state.get('periodo_b_label', '—')}" if ha_confronto else "")
)

current_data = pipe.current_data
old_data = pipe.old_data

# Terzo anno di confronto (due anni precedenti), stessa logica della pagina Nazioni
mostra_3_anno = False
periodo_a = st.session_state.get("sel_periodo_a")
y_2anni = None
data_2anni = current_data.iloc[0:0]
periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
conn = db.connect()
data_2anni, standalone_2anni = db.query_period(conn, *periodo_c, pipe.perimetro)
y_2anni = period_labels(3)[2]
if not data_2anni.empty:
    mostra_3_anno = True

st.caption(f"**{y_2anni}**: {periodo_c[0]} → {periodo_c[1]}")
if data_2anni.empty:
    st.caption("Nessun dato nel DB per 'due anni precedenti': il confronto a 3 vie resterà vuoto.")

# Tutte le nazioni presenti nei dati, incluse automaticamente (nessun selettore)
nazioni_scelte = rb.nazioni_disponibili(current_data, old_data, data_2anni)
if not nazioni_scelte:
    st.caption("Nessuna nazione trovata nei periodi selezionati.")
    st.stop()
st.info(f"Tutte le nazioni presenti nei dati sono incluse automaticamente: {len(nazioni_scelte)}.")

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
    )Re
