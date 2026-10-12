import plotly.express as px
import streamlit as st

from core import db, sku_search as sk
from core.design_system import page_setup, section, metric_cards, data_table, chart, empty_state, it_num
from core.report_builders import img_url
from core.ui_helpers import currency_col, number_col, percent_col, period_labels, shift_year

page_setup("Trova SKU", "🔎",
           "Analisi dettagliata di un articolo — SKU completo (13) o parziale (7 = codice, 9, 13)")

pipe = st.session_state.get("pipeline")
periodo_sel = st.session_state.get("sel_periodo_a")
perimetro = pipe.perimetro if pipe is not None else "1"

col_sku, col_ambito = st.columns([2, 3])
with col_sku:
    testo = st.text_input("SKU o parte iniziale", placeholder="es. FAL0012  ·  FAL001234  ·  FAL0012345678",
                          help="Lettere e cifre, senza trattini. 7 caratteri = codice articolo, 13 = SKU completo di colore/variante.")
with col_ambito:
    opzioni = ["Intero DB"]
    if periodo_sel:
        opzioni.insert(0, f"Periodo selezionato ({st.session_state.get('periodo_a_label', '—')})")
    ambito = st.radio("Ambito dell'analisi", opzioni, horizontal=True)
    if not periodo_sel:
        st.caption("Per analizzare il periodo selezionato applica prima il periodo nella barra in alto.")

prefisso = sk.normalizza_sku(testo)
if len(prefisso) < 3:
    empty_state("Inserisci almeno 3 caratteri dello SKU per avviare la ricerca.", "🔎")
    st.stop()
if len(prefisso) not in sk.LUNGHEZZE_CONSIGLIATE:
    st.caption(f"Ricerca per prefisso di {len(prefisso)} caratteri: vengono inclusi tutti gli SKU che iniziano con "
               f"**{prefisso}** (lunghezze tipiche: 7, 9, 13).")

intero_db = ambito == "Intero DB"
periodo = sk.FULL_DB_PERIOD if intero_db else tuple(periodo_sel)
conn = db.connect()
venduto, resi_fp = sk.cerca(conn, prefisso, periodo, perimetro)
if venduto.empty and resi_fp.empty:
    empty_state(f"Nessuna vendita o reso trovati per «{prefisso}» "
                f"{'nel DB' if intero_db else 'nel periodo selezionato'}.", "🔎")
    st.stop()

anagrafica = pipe.anagrafica if pipe is not None else (st.session_state.get("anagrafica") or db.get_anagrafica_dict(conn))

# ---------------------------------------------------------------- articoli trovati
trovati = sk.articoli_trovati(venduto, resi_fp, anagrafica)
section(f"Articoli trovati: {len(trovati)}",
        caption="Seleziona gli SKU da analizzare (di default tutti quelli che iniziano per il testo cercato).")
data_table(trovati, {"Fatturato": currency_col(), "Share %": percent_col(),
                     "Valore Medio Paio": currency_col(), "Paia spedite": number_col(),
                     "Paia rese": number_col(), "Paia nette": number_col(), "% Reso": percent_col()})
scelti = st.multiselect("SKU13 da includere", list(trovati["SKU"]), default=list(trovati["SKU"]))
if not scelti:
    st.info("Seleziona almeno uno SKU.")
    st.stop()
venduto = venduto[venduto["sku13"].astype(str).isin(scelti)]
resi_fp = resi_fp[resi_fp["sku13"].astype(str).isin(scelti)]

k = sk.kpi(venduto, resi_fp)
primo, ultimo = sk.date_vendita(venduto)

# ---------------------------------------------------------------- sintesi
if len(scelti) == 1:
    c_img, c_txt = st.columns([1, 4])
    c_img.image(img_url(scelti[0]), width=140)
    desc = trovati.loc[trovati["SKU"] == scelti[0], "Descrizione"].iloc[0]
    c_txt.markdown(f"### {scelti[0]}\n{desc}")

section("Sintesi",
        caption=("Intero DB" if intero_db else f"Periodo {st.session_state.get('periodo_a_label', '')}")
                + " · Fatturato = fatturato netto spedito − resi di vendite del periodo − resi di "
                  "vendite fuori periodo.")
metric_cards([
    {"label": "Fatturato", "value": f"{it_num(k['fattReale'], 2)} €"},
    {"label": "Paia nette reali", "value": it_num(k["paiaNette"])},
    {"label": "Valore medio paio", "value": f"{it_num(k['valMedio'], 2)} €"},
    {"label": "% Reso (Paia)", "value": f"{it_num(k['percReso'] * 100, 1)}%"},
    {"label": "% Reso (Valore)", "value": f"{it_num(k['percResoValore'] * 100, 1)}%"},
    {"label": "% Paia in promo", "value": f"{it_num(sk.percentuale_promo(venduto) * 100, 1)}%"},
])
st.table({
    "Metrica": ["Fatturato netto spedito", "− Resi di vendite del periodo", "− Resi di vendite fuori periodo",
                "Fatturato", "Paia spedite", "Paia rese", "Paia nette reali",
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

# ---------------------------------------------------------------- andamento mensile
section("Andamento mensile",
        caption="Venduto per mese di vendita, resi fuori periodo per mese di reso: la somma è il Fatturato.")
mensile = sk.per_mese(venduto, resi_fp)
mensile = mensile[mensile["Mese"] != "n.d."]
if not mensile.empty:
    fig = px.bar(mensile, x="Mese", y="Fatturato")
    chart(fig, y_title="Fatturato (€)")
    data_table(mensile, CONF)

# ---------------------------------------------------------------- dettaglio per dimensione
tab_taglia, tab_mkp, tab_naz, tab_canale, tab_sku = st.tabs(
    ["👟 Taglie", "🛍️ Marketplace", "🌍 Nazioni", "🚚 Canale", "🔢 Varianti (SKU13)"])
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

# ---------------------------------------------------------------- confronto anno precedente
if not intero_db:
    section("Confronto con l'anno precedente")
    y_curr, y_old = period_labels(2)
    periodo_prec = (shift_year(periodo[0], -1), shift_year(periodo[1], -1))
    v_old, r_old = sk.cerca(conn, prefisso, periodo_prec, perimetro)
    v_old = v_old[v_old["sku13"].astype(str).isin(scelti)]
    r_old = r_old[r_old["sku13"].astype(str).isin(scelti)]
    if v_old.empty and r_old.empty:
        st.caption(f"Nessun dato per questi SKU nel periodo {periodo_prec[0]} → {periodo_prec[1]}.")
    else:
        ko = sk.kpi(v_old, r_old)
        var = (k["fattReale"] / ko["fattReale"] - 1) if ko["fattReale"] else None
        st.table({
            "Metrica": ["Fatturato", "Paia nette", "% Reso (Paia)"],
            y_curr: [f"{it_num(k['fattReale'], 2)} €", it_num(k["paiaNette"]), f"{it_num(k['percReso'] * 100, 1)}%"],
            y_old: [f"{it_num(ko['fattReale'], 2)} €", it_num(ko["paiaNette"]), f"{it_num(ko['percReso'] * 100, 1)}%"],
        })
        if var is not None:
            st.caption(f"Variazione del Fatturato: **{it_num(var * 100, 1)}%** "
                       f"(periodo precedente {periodo_prec[0]} → {periodo_prec[1]}).")

# ---------------------------------------------------------------- righe
with st.expander("📄 Righe di dettaglio (ordini, resi) ed export"):
    righe = sk.dettaglio_righe(venduto, resi_fp)
    st.caption(f"{len(righe):,} righe".replace(",", ".") + (" — mostrate le prime 2.000." if len(righe) > 2000 else ""))
    data_table(righe.head(2000), {"Fatturato": currency_col(), "Paia spedite": number_col(),
                                  "Paia rese": number_col()})
    st.download_button("⬇️ Scarica le righe (CSV)",
                       data=righe.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                       file_name=f"sku_{prefisso}.csv", mime="text/csv")
