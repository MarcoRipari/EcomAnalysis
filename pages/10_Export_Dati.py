import streamlit as st

from core import db, export
from core.design_system import page_setup, section, empty_state
from core.ui_helpers import guard_pipeline, period_labels, shift_year

page_setup("Export Dati", "📤",
           "Export massivo CSV / Markdown per SCOPE, con colonne Anno e Mese — nessuna tabella a video")

pipe = guard_pipeline()

y_curr, y_old = period_labels(2)
periodo_a = st.session_state.get("sel_periodo_a")

# periodi dell'export: (etichetta anno, venduto, resi fuori periodo), dal più recente al più vecchio
periodi = [(y_curr, pipe.current_data, pipe.resi_fp_current)]
righe_info = [f"**{y_curr}**: {st.session_state.get('periodo_a_label', '—')}"]
if not pipe.old_data.empty or not pipe.resi_fp_old.empty:
    periodi.append((y_old, pipe.old_data, pipe.resi_fp_old))
    righe_info.append(f"**{y_old}**: {st.session_state.get('periodo_b_label', '—')}")
if periodo_a and st.session_state.get("sel_confronta_2anni", False):
    periodo_c = (shift_year(periodo_a[0], -2), shift_year(periodo_a[1], -2))
    data_2, resi_fp_2 = db.query_period(db.connect(), *periodo_c, pipe.perimetro)
    if not data_2.empty or not resi_fp_2.empty:
        y_2anni = period_labels(3)[2]
        periodi.append((y_2anni, data_2, resi_fp_2))
        righe_info.append(f"**{y_2anni}**: {periodo_c[0]} → {periodo_c[1]}")

st.markdown("<p class='ds-caption'>" + " · ".join(righe_info) + "</p>", unsafe_allow_html=True)

nazioni = export.nazioni_disponibili(periodi)
if not nazioni:
    empty_state("Nessun dato nei periodi selezionati.")
    st.stop()

section("Cosa contiene",
        caption="Una riga per ogni combinazione di Anno × Mese × SCOPE (DETAIL, MARKETPLACE_COUNTRY, "
                "MARKETPLACE_BRAND, COUNTRY_BRAND, GLOBAL_MARKETPLACE, GLOBAL_COUNTRY, GLOBAL_BRAND, "
                "GLOBAL). Il Fatturato è lo stesso della Dashboard: la somma di ogni SCOPE "
                "coincide con la riga GLOBAL. Share % = peso sul Fatturato della stessa fetta "
                "Anno/Mese. Var % YoY = confronto con la stessa fetta dell'anno precedente. "
                f"Sono incluse tutte le {len(nazioni)} nazioni presenti nei dati.")

livello = st.radio(
    "Dettaglio temporale",
    ["Un valore per l'intero periodo (Mese = “Tutto il periodo”)", "Una riga per ogni mese del periodo"],
    horizontal=True,
)
mensile = livello.startswith("Una riga")

if st.button("Prepara export", type="primary"):
    with st.spinner("Calcolo dell'export…"):
        df = export.build_export(periodi, nazioni, mensile=mensile)
    st.session_state["export_df"] = df
    st.session_state["export_mensile"] = mensile

df = st.session_state.get("export_df")
if df is not None:
    if df.empty:
        empty_state("Nessun dato disponibile per l'export.")
    else:
        suffisso = "mensile" if st.session_state.get("export_mensile") else "periodo"
        st.success(f"Export pronto: {len(df):,} righe.".replace(",", "."))
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ Scarica CSV", data=export.to_csv(df), mime="text/csv",
                           file_name=f"export_fatturato_reale_{suffisso}.csv",
                           width="stretch")
        c2.download_button("⬇️ Scarica Markdown",
                           data=("# Export Fatturato — Marketplace × Nazione × Brand\n\n"
                                 + export.to_markdown(df)).encode("utf-8"),
                           mime="text/markdown", file_name=f"export_fatturato_reale_{suffisso}.md",
                           width="stretch")
