import streamlit as st

from core import metrics as met
from core import aggregations as agg
from core import report_builders as rb
from core.design_system import page_setup, section, metric_cards, data_table, chart, it_num
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels

page_setup("Dashboard", "📊",
           "Dettaglio fatturato — anno corrente · perimetro e periodo scelti in Carica Dati")

pipe = guard_pipeline()
y_curr, _ = period_labels(1)[0], None

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

    metric_cards([
        {"label": f"Fatturato netto reale ({label})", "value": f"{it_num(fatt_reale, 2)} €"},
        {"label": "Ordini", "value": it_num(m[canale]["ordini"])},
        {"label": "Paia nette", "value": it_num(m[canale]["paiaNet"])},
    ])

    section("Dettaglio fatturato")
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

    metric_cards([
        {"label": "Fatturato netto reale — totale", "value": f"{it_num(fatt_reale_tot, 2)} €"},
        {"label": "— Diretti", "value": f"{it_num(fatt_reale_dir, 2)} €"},
        {"label": "— Esterni", "value": f"{it_num(fatt_reale_est, 2)} €"},
    ])

    section("Dettaglio fatturato")
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

st.markdown(
    f"Resi riconciliati (Spedito→Reso): **{len(esito['convertiti'])}** · "
    f"Duplicati scartati: **{len(esito['duplicati'])}** · "
    f"Rimborsi extra: **{len(esito['standalone'])}** · "
    f"Fuori periodo: **{len(esito['fuoriPeriodo'])}**"
)

section("Marketplace")
data_table(rb.single_year_table(agg.aggregate_by_key(current_data, "mkp"), y_curr, "fatturatoNetto"),
           {"% Reso": percent_col(), f"Fatturato Netto {y_curr}": currency_col(),
            "Scontrino Medio": currency_col()})

section("Nazioni")
data_table(rb.single_year_table(agg.aggregate_by_key(current_data, "nazione"), y_curr, "fatturatoNetto"),
           {"% Reso": percent_col(), f"Fatturato Netto {y_curr}": currency_col(),
            "Scontrino Medio": currency_col()})

section("Collezioni")
data_table(rb.single_year_table(agg.aggregate_by_key(current_data, "clzMappata"), y_curr, "paiaNette"),
           {"% Reso": percent_col(), f"Fatturato Netto {y_curr}": currency_col(),
            "Scontrino Medio": currency_col()})

section("Top articoli — anno corrente",
       caption="Classifica per fatturato netto reale, con foto articolo e resi.")
top_n = st.slider("Numero di articoli da mostrare", 10, 500, 50, step=10)
top_df = rb.top_articoli_dashboard(current_data, pipe.anagrafica, top_n=5000)
data_table(top_df.head(top_n), {
    "Foto": image_col(), "% Reso": percent_col(), "Fatturato Netto": currency_col(),
    "Paia Spedite": number_col(), "Paia Rese": number_col(), "Paia Nette": number_col(),
})
