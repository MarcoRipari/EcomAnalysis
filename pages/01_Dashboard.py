import streamlit as st

from core import aggregations as agg
from core import metrics as met
from core import report_builders as rb
from core.design_system import page_setup, section, metric_cards, data_table, it_num
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels

page_setup("Dashboard", None)

pipe = guard_pipeline()
y_curr = period_labels(1)[0]
current_data, resi_fp = pipe.current_data, pipe.resi_fp_current

kpi = met.kpi_per_canale(current_data, resi_fp)
perimetro = pipe.perimetro


def euro(x: float) -> str:
    return f"{it_num(x, 2)} €"


def pct(x: float) -> str:
    return f"{it_num(x * 100, 1)}%"


if perimetro != "1":
    nome = st.session_state.get("perimetro_label") or ("Canali Diretti" if perimetro in ("2", "DIRETTO") else "Canale Esterno")
    k = kpi["tot"]
    metric_cards([
        {"label": f"Fatturato ({nome})", "value": euro(k["fattReale"])},
        {"label": "Paia Nette", "value": it_num(k["paiaNette"])},
        {"label": "Valore Medio Paio", "value": euro(k["valMedio"])},
        {"label": "Scontrino Medio", "value": euro(k["scontrinoMedio"])},
        {"label": "% Reso (Paia)", "value": pct(k["percReso"])},
        {"label": "% Reso (Valore)", "value": pct(k["percResoValore"])},
    ])
    colonne = {nome: k}
else:
    metric_cards([
        {"label": "Fatturato Totale", "value": euro(kpi["tot"]["fattReale"])},
        {"label": "Canali Diretti", "value": euro(kpi["dir"]["fattReale"])},
        {"label": "Marketplace Esterni", "value": euro(kpi["est"]["fattReale"])},
        {"label": "Paia Nette", "value": it_num(kpi["tot"]["paiaNette"])},
        {"label": "Scontrino Medio", "value": euro(kpi["tot"]["scontrinoMedio"])},
        {"label": "% Reso (Paia)", "value": pct(kpi["tot"]["percReso"])},
        {"label": "% Reso (Valore)", "value": pct(kpi["tot"]["percResoValore"])},
    ])
    colonne = {"Totale": kpi["tot"], "Canali Diretti": kpi["dir"], "Marketplace Esterni": kpi["est"]}

section("Composizione Fatturato")
righe = [
    ("Fatturato lordo (IVA inclusa)", lambda k: euro(k["lordo"])),
    ("Fatturato netto spedito", lambda k: euro(k["nettoSpedito"])),
    ("Resi del periodo", lambda k: euro(-k["resiPeriodo"])),
    ("Resi fuori periodo", lambda k: euro(-k["resiFuoriPeriodo"])),
    ("Fatturato Netto", lambda k: euro(k["fattReale"])),
    ("Paia spedite", lambda k: it_num(k["paiaSped"])),
    ("Paia rese", lambda k: it_num(k["paiaRes"])),
    ("Paia nette", lambda k: it_num(k["paiaNette"])),
    ("Valore medio paio", lambda k: euro(k["valMedio"])),
    ("Scontrino medio", lambda k: euro(k["scontrinoMedio"])),
    ("% Reso (Paia)", lambda k: pct(k["percReso"])),
    ("% Reso (Valore)", lambda k: pct(k["percResoValore"])),
]
tabella = {"Metrica": [r[0] for r in righe]}
for nome_col, k in colonne.items():
    tabella[nome_col] = [fmt(k) for _, fmt in righe]
st.table(tabella)

section("Ripartizione Fatturato")
conf = {"% Reso": percent_col(), f"Fatturato {y_curr}": currency_col(),
        "Valore Medio Paio": currency_col(), "Scontrino Medio": currency_col(), "Paia Spedite": number_col(),
        "Paia Rese": number_col(), "Paia Nette": number_col()}
tab_mkp, tab_naz, tab_clz = st.tabs(["Marketplace", "Nazioni", "Collezioni"])
for tab, chiave in ((tab_mkp, "mkp"), (tab_naz, "nazione"), (tab_clz, "clzMappata")):
    with tab:
        data_table(rb.single_year_table(agg.aggregate_by_key(current_data, chiave, resi_fp),
                                        y_curr, "fatturatoNetto"), conf)

section("Top Articoli")
top_n = st.slider("Numero di articoli da mostrare", 10, 500, 50, step=10)
top_df = rb.top_articoli_dashboard(current_data, pipe.anagrafica, top_n=top_n, resi_fp_data=resi_fp)
data_table(top_df, {
    "Foto": image_col(), "% Reso": percent_col(), "Fatturato": currency_col(),
    "Paia Spedite": number_col(), "Paia Rese": number_col(), "Paia Nette": number_col(),
})
