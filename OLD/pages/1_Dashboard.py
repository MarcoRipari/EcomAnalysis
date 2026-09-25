import streamlit as st

from core import metrics as met
from core import aggregations as agg
from core import report_builders as rb
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, years

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("📊 Dashboard — Dettaglio Fatturato Anno Corrente")

pipe = guard_pipeline()
y_curr, _ = years()

current_data = pipe.current_data
m = met.calculate_global_metrics_detailed(current_data)
m_resi_extra = met.calculate_global_metrics_detailed(pipe.esito_resi_current["standalone"])
esito = pipe.esito_resi_current
grezze = pipe.metriche_grezze_current

perimetro = pipe.perimetro
if perimetro in ("2", "3"):
    canale = "dir" if perimetro == "2" else "est"
    label = "DIRETTI" if perimetro == "2" else "ESTERNI"
    fatt_reale = m[canale]["netto"] + m_resi_extra[canale]["netto"]

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Fatturato Netto Reale ({label})", f"€ {fatt_reale:,.2f}")
    c2.metric("Ordini", f"{m[canale]['ordini']:,}")
    c3.metric("Paia Nette", f"{m[canale]['paiaNet']:,.0f}")

    st.subheader("Dettaglio fatturato")
    st.table({
        "Metrica": ["Fatturato Lordo", "Fatturato Netto — pre riconciliazione",
                    "Fatturato Netto — dopo riconciliazione RESI", "Rimborsi extra non abbinati",
                    "Fatturato Netto Reale", "Totale Ordini", "Paia Spedite", "Paia Rese", "Paia Nette"],
        label: [m[canale]["lordo"], grezze[canale]["netto"], m[canale]["netto"],
                m_resi_extra[canale]["netto"], fatt_reale, m[canale]["ordini"],
                m[canale]["paiaSped"], m[canale]["paiaRes"], m[canale]["paiaNet"]],
    })
else:
    fatt_reale_tot = m["tot"]["netto"] + m_resi_extra["tot"]["netto"]
    fatt_reale_dir = m["dir"]["netto"] + m_resi_extra["dir"]["netto"]
    fatt_reale_est = m["est"]["netto"] + m_resi_extra["est"]["netto"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Fatturato Netto Reale — Totale", f"€ {fatt_reale_tot:,.2f}")
    c2.metric("— Diretti", f"€ {fatt_reale_dir:,.2f}")
    c3.metric("— Esterni", f"€ {fatt_reale_est:,.2f}")

    st.subheader("Dettaglio fatturato")
    st.table({
        "Metrica": ["Fatturato Lordo", "Fatturato Netto — pre riconciliazione",
                    "Fatturato Netto — dopo riconciliazione RESI", "Rimborsi extra non abbinati",
                    "Fatturato Netto Reale", "Totale Ordini", "Paia Spedite", "Paia Rese", "Paia Nette"],
        "Totale": [m["tot"]["lordo"], grezze["tot"]["netto"], m["tot"]["netto"], m_resi_extra["tot"]["netto"],
                   fatt_reale_tot, m["tot"]["ordini"], m["tot"]["paiaSped"], m["tot"]["paiaRes"], m["tot"]["paiaNet"]],
        "Diretti": [m["dir"]["lordo"], grezze["dir"]["netto"], m["dir"]["netto"], m_resi_extra["dir"]["netto"],
                    fatt_reale_dir, m["dir"]["ordini"], m["dir"]["paiaSped"], m["dir"]["paiaRes"], m["dir"]["paiaNet"]],
        "Esterni": [m["est"]["lordo"], grezze["est"]["netto"], m["est"]["netto"], m_resi_extra["est"]["netto"],
                    fatt_reale_est, m["est"]["ordini"], m["est"]["paiaSped"], m["est"]["paiaRes"], m["est"]["paiaNet"]],
    })

st.caption(
    f"Resi riconciliati (Spedito→Reso): **{len(esito['convertiti'])}** · "
    f"Duplicati scartati: **{len(esito['duplicati'])}** · "
    f"Rimborsi extra: **{len(esito['standalone'])}** · "
    f"Fuori periodo: **{len(esito['fuoriPeriodo'])}**"
)

st.divider()
st.subheader("📦 Dettaglio Marketplace")
st.dataframe(rb.single_year_table(agg.aggregate_by_key(current_data, "mkp"), y_curr, "fatturatoNetto"),
             hide_index=True, use_container_width=True,
             column_config={"% Reso": percent_col(), f"Fatturato Netto {y_curr}": currency_col(),
                             "Scontrino Medio": currency_col()})

st.subheader("🌍 Dettaglio Nazioni")
st.dataframe(rb.single_year_table(agg.aggregate_by_key(current_data, "nazione"), y_curr, "fatturatoNetto"),
             hide_index=True, use_container_width=True,
             column_config={"% Reso": percent_col(), f"Fatturato Netto {y_curr}": currency_col(),
                             "Scontrino Medio": currency_col()})

st.subheader("📈 Dettaglio Collezioni")
st.dataframe(rb.single_year_table(agg.aggregate_by_key(current_data, "clzMappata"), y_curr, "paiaNette"),
             hide_index=True, use_container_width=True,
             column_config={"% Reso": percent_col(), f"Fatturato Netto {y_curr}": currency_col(),
                             "Scontrino Medio": currency_col()})

st.divider()
st.subheader("🏆 Top Articoli — Anno Corrente")
top_n = st.slider("Numero di articoli da mostrare", 10, 500, 50, step=10)
top_df = rb.top_articoli_dashboard(current_data, pipe.anagrafica, top_n=5000)
st.dataframe(top_df.head(top_n), hide_index=True, use_container_width=True,
             column_config={
                 "Foto": image_col(), "% Reso": percent_col(), "Fatturato Netto": currency_col(),
                 "Paia Spedite": number_col(), "Paia Rese": number_col(), "Paia Nette": number_col(),
             })
