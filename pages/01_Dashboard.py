import streamlit as st

from core import aggregations as agg
from core import metrics as met
from core import report_builders as rb
from core.design_system import page_setup, section, metric_cards, data_table, it_num
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels

page_setup("Dashboard", "📊",
           "Sintesi del Fatturato — periodo e perimetro scelti nella barra in alto")

pipe = guard_pipeline()
y_curr = period_labels(1)[0]
current_data, resi_fp = pipe.current_data, pipe.resi_fp_current

kpi = met.kpi_per_canale(current_data, resi_fp)
perimetro = pipe.perimetro


def euro(x: float) -> str:
    return f"{it_num(x, 2)} €"


def pct(x: float) -> str:
    return f"{it_num(x * 100, 1)}%"


if perimetro in ("2", "3"):
    canale, nome = ("dir", "Diretti") if perimetro == "2" else ("est", "Esterni")
    k = kpi[canale]
    metric_cards([
        {"label": f"Fatturato — {nome}", "value": euro(k["fattReale"])},
        {"label": "Paia nette reali", "value": it_num(k["paiaNette"])},
        {"label": "Valore medio paio", "value": euro(k["valMedio"])},
        {"label": "Scontrino medio", "value": euro(k["scontrinoMedio"])},
        {"label": "% Reso (Paia)", "value": pct(k["percReso"])},
        {"label": "% Reso (Valore)", "value": pct(k["percResoValore"])},
    ])
    colonne = {nome: kpi[canale]}
else:
    metric_cards([
        {"label": "Fatturato — totale", "value": euro(kpi["tot"]["fattReale"])},
        {"label": "— Canale Diretti", "value": euro(kpi["dir"]["fattReale"])},
        {"label": "— Canale Esterni (Marketplace)", "value": euro(kpi["est"]["fattReale"])},
        {"label": "Paia nette reali", "value": it_num(kpi["tot"]["paiaNette"])},
        {"label": "Scontrino medio", "value": euro(kpi["tot"]["scontrinoMedio"])},
        {"label": "% Reso (Paia)", "value": pct(kpi["tot"]["percReso"])},
        {"label": "% Reso (Valore)", "value": pct(kpi["tot"]["percResoValore"])},
    ])
    colonne = {"Totale": kpi["tot"], "Diretti": kpi["dir"], "Esterni": kpi["est"]}

section("Come si compone il Fatturato",
        caption="Fatturato = fatturato netto spedito − resi di vendite del periodo − resi di "
                "vendite fuori periodo (resi con data nel periodo, ma venduti prima del periodo).")
righe = [
    ("Fatturato lordo (IVA inclusa)", lambda k: euro(k["lordo"])),
    ("Fatturato netto spedito", lambda k: euro(k["nettoSpedito"])),
    ("− Resi di vendite del periodo", lambda k: euro(-k["resiPeriodo"])),
    ("− Resi di vendite fuori periodo", lambda k: euro(-k["resiFuoriPeriodo"])),
    ("Fatturato", lambda k: euro(k["fattReale"])),
    ("Paia spedite", lambda k: it_num(k["paiaSped"])),
    ("Paia rese", lambda k: it_num(k["paiaRes"])),
    ("Paia nette reali", lambda k: it_num(k["paiaNette"])),
    ("Valore medio paio", lambda k: euro(k["valMedio"])),
    ("Scontrino medio", lambda k: euro(k["scontrinoMedio"])),
    ("% Reso (Paia)", lambda k: pct(k["percReso"])),
    ("% Reso (Valore)", lambda k: pct(k["percResoValore"])),
]
tabella = {"Metrica": [r[0] for r in righe]}
for nome_col, k in colonne.items():
    tabella[nome_col] = [fmt(k) for _, fmt in righe]
st.table(tabella)

section("Ripartizione del Fatturato")
conf = {"% Reso": percent_col(), f"Fatturato {y_curr}": currency_col(),
        "Valore Medio Paio": currency_col(), "Scontrino Medio": currency_col(), "Paia Spedite": number_col(),
        "Paia Rese": number_col(), "Paia Nette": number_col()}
tab_mkp, tab_naz, tab_clz = st.tabs(["Marketplace", "Nazioni", "Collezioni"])
for tab, chiave in ((tab_mkp, "mkp"), (tab_naz, "nazione"), (tab_clz, "clzMappata")):
    with tab:
        data_table(rb.single_year_table(agg.aggregate_by_key(current_data, chiave, resi_fp),
                                        y_curr, "fatturatoNetto"), conf)

section("Top articoli",
        caption="Classifica per Fatturato, con foto articolo e resi (compresi i resi fuori periodo).")
top_n = st.slider("Numero di articoli da mostrare", 10, 500, 50, step=10)
top_df = rb.top_articoli_dashboard(current_data, pipe.anagrafica, top_n=top_n, resi_fp_data=resi_fp)
data_table(top_df, {
    "Foto": image_col(), "% Reso": percent_col(), "Fatturato": currency_col(),
    "Paia Spedite": number_col(), "Paia Rese": number_col(), "Paia Nette": number_col(),
})
