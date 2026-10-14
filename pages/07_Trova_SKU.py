import plotly.express as px
import streamlit as st

from core import db, sku_search as sk
from core.design_system import page_setup, section, metric_cards, data_table, chart, empty_state, it_num
from core.report_builders import img_url
from core.ui_helpers import currency_col, number_col, percent_col, period_labels, shift_year

page_setup("Trova SKU", None)

pipe = st.session_state.get("pipeline")
periodo_sel = st.session_state.get("sel_periodo_a")
perimetro = pipe.perimetro if pipe is not None else "1"

col_sku, col_ambito = st.columns([2, 3])
with col_sku:
    testo = st.text_input("Codice Articolo / SKU", placeholder="es. FAL0012 o 0503354")
with col_ambito:
    opzioni = ["Storico Completo"]
    if periodo_sel:
        opzioni.insert(0, "Periodo Attivo")
    ambito = st.radio("Ambito", opzioni, horizontal=True)

prefisso = sk.normalizza_sku(testo)
if len(prefisso) < 3:
    empty_state("Inserisci almeno 3 caratteri dello SKU per avviare la ricerca.")
    st.stop()

intero_db = ambito == "Storico Completo"
periodo = sk.FULL_DB_PERIOD if intero_db else tuple(periodo_sel)
conn = db.connect()
venduto, resi_fp = sk.cerca(conn, prefisso, periodo, perimetro)
if venduto.empty and resi_fp.empty:
    empty_state(f"Nessun dato per «{prefisso}».")
    st.stop()

anagrafica = pipe.anagrafica if pipe is not None else (st.session_state.get("anagrafica") or db.get_anagrafica_dict(conn))

# Articoli trovati
trovati = sk.articoli_trovati(venduto, resi_fp, anagrafica)
section(f"Articoli Trovati ({len(trovati)})")
data_table(trovati, {"Fatturato": currency_col(), "Share %": percent_col(),
                     "Valore Medio Paio": currency_col(), "Paia spedite": number_col(),
                     "Paia rese": number_col(), "Paia nette": number_col(), "% Reso": percent_col()})
scelti = st.multiselect("Filtra per SKU13", list(trovati["SKU"]), default=list(trovati["SKU"]))
if not scelti:
    st.info("Seleziona almeno uno SKU.")
    st.stop()
venduto = venduto[venduto["sku13"].astype(str).isin(scelti)]
resi_fp = resi_fp[resi_fp["sku13"].astype(str).isin(scelti)]

k = sk.kpi(venduto, resi_fp)
primo, ultimo = sk.date_vendita(venduto)

# Sintesi
if len(scelti) == 1:
    c_img, c_txt = st.columns([1, 4])
    c_img.image(img_url(scelti[0]), width=140)
    desc = trovati.loc[trovati["SKU"] == scelti[0], "Descrizione"].iloc[0]
    c_txt.markdown(f"### {scelti[0]}\n{desc}")

section("Sintesi")
metric_cards([
    {"label": "Fatturato", "value": f"{it_num(k['fattReale'], 2)} €"},
    {"label": "Paia Nette", "value": it_num(k["paiaNette"])},
    {"label": "Valore Medio Paio", "value": f"{it_num(k['valMedio'], 2)} €"},
    {"label": "% Reso (Paia)", "value": f"{it_num(k['percReso'] * 100, 1)}%"},
    {"label": "% Reso (Valore)", "value": f"{it_num(k['percResoValore'] * 100, 1)}%"},
    {"label": "% Paia in Promo", "value": f"{it_num(sk.percentuale_promo(venduto) * 100, 1)}%"},
])
st.table({
    "Metrica": ["Fatturato netto spedito", "Resi del periodo", "Resi fuori periodo",
                "Fatturato Netto", "Paia spedite", "Paia rese", "Paia nette",
                "Prima vendita", "Ultima vendita"],
    "Valore": [f"{it_num(k['nettoSpedito'], 2)} €", f"{it_num(-k['resiPeriodo'], 2)} €",
               f"{it_num(-k['resiFuoriPeriodo'], 2)} €", f"{it_num(k['fattReale'], 2)} €",
               it_num(k["paiaSped"]), it_num(k["paiaRes"]), it_num(k["paiaNette"]),
               primo.strftime("%d/%m/%Y") if primo is not None else "—",
               ultimo.strftime("%d/%m/%Y") if ultimo is not None else "—"],
})

CONF = {"Fatturato": currency_col(), "Share %": percent_col(), "Valore Medio Paio": currency_col(),
        "Paia spedite": number_col(), "Paia rese": number_col(), "Paia nette": number_col(),
        "% Reso": percent_col()}

# Andamento mensile
section("Andamento Mensile")
mensile = sk.per_mese(venduto, resi_fp)
mensile = mensile[mensile["Mese"] != "n.d."]
if not mensile.empty:
    fig = px.bar(mensile, x="Mese", y="Fatturato")
    chart(fig, y_title="Fatturato (€)")
    data_table(mensile, CONF)

# Dettaglio per dimensione
tab_taglia, tab_mkp, tab_naz, tab_canale, tab_sku = st.tabs(
    ["Taglie", "Marketplace", "Nazioni", "Canale", "Varianti (SKU13)"])
with tab_taglia:
    data_table(sk.per_taglia(venduto, resi_fp), CONF)
with tab_mkp:
    data_table(sk.per_dimensione(venduto, resi_fp, "Marketplace"), CONF)
with tab_naz:
    data_table(sk.per_dimensione(venduto, resi_fp, "Nazione"), CONF)
with tab_canale:
    data_table(sk.per_dimensione(venduto, resi_fp, "Canale"), CONF)
with tab_sku:
    data_table(sk.per_dimensione(venduto, resi_fp, "SKU"), CONF)

# Confronto anno precedente
if not intero_db:
    section("Confronto Anno Precedente")
    y_curr, y_old = period_labels(2)
    periodo_prec = (shift_year(periodo[0], -1), shift_year(periodo[1], -1))
    v_old, r_old = sk.cerca(conn, prefisso, periodo_prec, perimetro)
    v_old = v_old[v_old["sku13"].astype(str).isin(scelti)]
    r_old = r_old[r_old["sku13"].astype(str).isin(scelti)]
    if v_old.empty and r_old.empty:
        st.caption(f"Nessun dato nel periodo {periodo_prec[0]} - {periodo_prec[1]}.")
    else:
        ko = sk.kpi(v_old, r_old)
        var = (k["fattReale"] / ko["fattReale"] - 1) if ko["fattReale"] else None
        st.table({
            "Metrica": ["Fatturato", "Paia nette", "% Reso (Paia)"],
            y_curr: [f"{it_num(k['fattReale'], 2)} €", it_num(k["paiaNette"]), f"{it_num(k['percReso'] * 100, 1)}%"],
            y_old: [f"{it_num(ko['fattReale'], 2)} €", it_num(ko["paiaNette"]), f"{it_num(ko['percReso'] * 100, 1)}%"],
        })
        if var is not None:
            st.caption(f"Variazione Fatturato: **{it_num(var * 100, 1)}%**.")

# Righe di dettaglio
with st.expander("Dettaglio Ordini e Resi"):
    righe = sk.dettaglio_righe(venduto, resi_fp)
    st.caption(f"{len(righe):,} righe".replace(",", "."))
    data_table(righe.head(2000), {"Fatturato": currency_col(), "Paia spedite": number_col(),
                                  "Paia rese": number_col()})
    st.download_button("Scarica CSV",
                       data=righe.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                       file_name=f"sku_{prefisso}.csv", mime="text/csv")
