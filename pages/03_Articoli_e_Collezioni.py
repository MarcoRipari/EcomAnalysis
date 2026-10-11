import streamlit as st

from core import aggregations as agg
from core import esplora, metrics as met
from core import report_builders as rb
from core.design_system import page_setup, section, data_table, empty_state, metric_cards, it_num
from core.ui_helpers import guard_pipeline, currency_col, percent_col, number_col, image_col, period_labels

page_setup("Articoli & Collezioni", "🌳",
           "Analisi approfondita per Collezione, Codice Articolo (SKU7) e Carryover — Confronto Y2Y")

pipe = guard_pipeline()
y_curr, y_old = period_labels(2)

if pipe.old_data.empty:
    empty_state(
        "L'anno−1 non è coperto dal DB: non ci sono dati storici da confrontare. "
        "Scegli un periodo il cui anno precedente sia presente nel DB in Carica Dati.",
        "⚠️"
    )
    st.stop()

st.markdown(
    f"<p class='ds-caption'><b>{y_curr}</b>: {st.session_state.get('periodo_a_label', '—')} · "
    f"<b>{y_old}</b>: {st.session_state.get('periodo_b_label', '—')}</p>",
    unsafe_allow_html=True,
)

current_data = pipe.current_data
old_data = pipe.old_data
st_curr = pipe.resi_fp_current
st_old = pipe.resi_fp_old

# Barra di controllo: filtro perimetro carryover
col_ctrl1, col_ctrl2 = st.columns([1, 2])
with col_ctrl1:
    modalita = st.radio(
        "Filtro Articoli",
        ["Tutti gli articoli", "Solo Carryover (venduti in entrambi gli anni)"],
        horizontal=False
    )
is_carryover = (modalita == "Solo Carryover (venduti in entrambi gli anni)")

if is_carryover:
    co_dict = agg.filter_carryover_data(current_data, old_data, st_curr, st_old)
    curr_view = co_dict["curr"]
    old_view = co_dict["old"]
    st_curr_view = co_dict["resi_fp_curr"]
    st_old_view = co_dict["resi_fp_old"]
    num_skus = curr_view["sku13"].nunique() if not curr_view.empty else 0
    with col_ctrl2:
        st.info(f"♻️ Modalità Carryover attiva: **{num_skus:,}** SKU13 venduti in entrambe le stagioni.".replace(",", "."))
else:
    curr_view = current_data
    old_view = old_data
    st_curr_view = st_curr
    st_old_view = st_old
    num_skus = curr_view["sku13"].nunique() if not curr_view.empty else 0
    with col_ctrl2:
        st.caption(f"Visualizzazione completa: **{num_skus:,}** SKU13 totali nel periodo corrente.".replace(",", "."))

tab_albero, tab_codici, tab_top_flop = st.tabs([
    "🔎 Esplora per Marketplace · Nazione · Brand · Collezione",
    "🔢 Performance Codici SKU7",
    "🏆 Top & Flop (Best Seller & Resi Critici)",
])

CONF_ESPLORA = {
    f"Fatturato {y_curr}": currency_col(), f"Fatturato {y_old}": currency_col(),
    f"% Tot {y_curr}": percent_col(), f"% Tot {y_old}": percent_col(),
    f"% Reso {y_curr}": percent_col(), f"% Reso {y_old}": percent_col(),
    "VAR% FATT": percent_col(), "VAR% PAIA": percent_col(),
    f"Paia Nette {y_curr}": number_col(), f"Paia Nette {y_old}": number_col(),
}

with tab_albero:
    st.caption("Scegli i filtri (ognuno mostra solo i valori compatibili con le scelte precedenti; "
               "vuoto = tutti) e le dimensioni per cui raggruppare le righe.")
    frames = [curr_view, st_curr_view, old_view, st_old_view]
    filtri: dict[str, list[str]] = {}
    colonne_filtri = st.columns(len(esplora.DIMENSIONI))
    for (etichetta, colonna), box in zip(esplora.DIMENSIONI.items(), colonne_filtri):
        chiave = f"esp_{colonna}"
        disponibili = esplora.opzioni(frames, colonna, filtri)        # compatibili con i filtri a sinistra
        # un valore scelto prima e non più compatibile con i filtri precedenti viene scartato
        st.session_state[chiave] = [v for v in st.session_state.get(chiave, []) if v in disponibili]
        filtri[colonna] = box.multiselect(etichetta, disponibili, key=chiave, placeholder="Tutti")
    raggruppa = st.multiselect("Raggruppa per", list(esplora.DIMENSIONI), default=["Brand", "Collezione"],
                               key="esp_raggruppa",
                               help="Le righe della tabella sono le combinazioni delle dimensioni scelte. "
                                    "Senza dimensioni vedi un solo totale per i filtri selezionati.")

    tab = esplora.tabella((curr_view, st_curr_view), (old_view, st_old_view), filtri, raggruppa, y_curr, y_old)
    kc = met.kpi_reali(esplora.filtra(curr_view, filtri), esplora.filtra(st_curr_view, filtri))
    ko = met.kpi_reali(esplora.filtra(old_view, filtri), esplora.filtra(st_old_view, filtri))
    metric_cards([
        {"label": f"Fatturato {y_curr}", "value": f"{it_num(kc['fattReale'], 2)} €"},
        {"label": f"Fatturato {y_old}", "value": f"{it_num(ko['fattReale'], 2)} €"},
        {"label": f"Paia nette {y_curr}", "value": it_num(kc["paiaNette"])},
        {"label": f"% Reso {y_curr}", "value": f"{it_num(kc['percReso'] * 100, 1)}%"},
        {"label": f"Scontrino medio {y_curr}", "value": f"{it_num(kc['scontrinoMedio'], 2)} €"},
    ])
    if tab.empty:
        empty_state("Nessun dato per questa combinazione di filtri.")
    else:
        st.caption(f"{len(tab):,} righe".replace(",", "."))
        data_table(tab, CONF_ESPLORA)


with tab_codici:
    section("Comparativa Codici Articolo (SKU7)")
    df_codici = rb.comparativa_codici(
        curr_view, old_view, pipe.anagrafica, y_curr, y_old,
        resi_fp_current=st_curr_view, resi_fp_old=st_old_view
    )

    col_search, col_sort = st.columns([2, 1])
    with col_search:
        filtro_txt = st.text_input("🔎 Cerca per codice, collezione o descrizione", key="filtro_sku7")
    with col_sort:
        ordinamento = st.selectbox(
            "Ordina per",
            [f"Fatturato {y_curr}", f"Paia Nette {y_curr}", f"% Reso {y_curr}", "VAR% FATT"],
            index=0
        )

    if not df_codici.empty:
        if filtro_txt:
            mask = df_codici.apply(lambda r: filtro_txt.lower() in " ".join(str(v) for v in r.values).lower(), axis=1)
            df_codici = df_codici[mask]

        sort_map = {
            f"Fatturato {y_curr}": f"Fatturato {y_curr}",
            f"Paia Nette {y_curr}": f"Paia Net {y_curr}",
            f"% Reso {y_curr}": f"% Reso {y_curr}",
            "VAR% FATT": "VAR% FATT",
        }
        col_sort_real = sort_map.get(ordinamento, f"Fatturato {y_curr}")
        df_codici = df_codici.sort_values(col_sort_real, ascending=False).reset_index(drop=True)

        st.caption(f"Trovati {len(df_codici):,} codici articolo".replace(",", "."))
        data_table(
            df_codici,
            {
                "Foto": image_col(),
                f"Fatturato {y_curr}": currency_col(),
                f"Fatturato {y_old}": currency_col(),
                f"% Reso {y_curr}": percent_col(),
                f"% Reso {y_old}": percent_col(),
                "VAR% FATT": percent_col(),
                f"Paia Net {y_curr}": number_col(),
                f"Paia Net {y_old}": number_col(),
            }
        )
    else:
        empty_state("Nessun articolo trovato.")


with tab_top_flop:
    section("Analisi Strategica: Best Seller vs Resi Critici",
            caption="Resi critici: articoli con almeno 10 paia nette (in mancanza, tutti gli articoli).")

    df_base = rb.comparativa_codici(
        curr_view, old_view, pipe.anagrafica, y_curr, y_old,
        resi_fp_current=st_curr_view, resi_fp_old=st_old_view
    )

    if not df_base.empty:
        c_top, c_flop = st.columns(2)

        with c_top:
            st.subheader("🥇 Top 15 Best Seller (per Fatturato)")
            top_seller = df_base.sort_values(f"Fatturato {y_curr}", ascending=False).head(15).reset_index(drop=True)
            data_table(
                top_seller,
                {
                    "Foto": image_col(),
                    f"Fatturato {y_curr}": currency_col(),
                    f"Paia Net {y_curr}": number_col(),
                    f"% Reso {y_curr}": percent_col(),
                    "VAR% FATT": percent_col(),
                }
            )

        with c_flop:
            st.subheader("⚠️ Top 15 Articoli con Tasso di Reso più Alto")
            # Filtro minimo paia spedite per evitare falsi positivi su articoli con 1 vendita e 1 reso (100%)
            flop_df = df_base[df_base[f"Paia Net {y_curr}"] >= 10].sort_values(f"% Reso {y_curr}", ascending=False).head(15).reset_index(drop=True)
            if flop_df.empty:
                flop_df = df_base.sort_values(f"% Reso {y_curr}", ascending=False).head(15).reset_index(drop=True)

            data_table(
                flop_df,
                {
                    "Foto": image_col(),
                    f"% Reso {y_curr}": percent_col(),
                    f"Paia Net {y_curr}": number_col(),
                    f"Fatturato {y_curr}": currency_col(),
                    "VAR% FATT": percent_col(),
                }
            )
    else:
        empty_state("Nessun dato per la classifica Top/Flop.")
