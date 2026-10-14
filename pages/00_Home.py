import streamlit as st

from core import db, ferie, settings
from core.design_system import page_setup, section, metric_cards, it_num

page_setup("Homepage", None)

conn = db.connect()
ferie.init_ferie_tables(conn)

# Identificazione utente corrente per preferenze persistenti
sess = st.session_state.get("auth", {}).get("user", {}) or {}
user_email = st.session_state.get("user_email") or sess.get("email", "")

# Recupera configurazione ordinamento e visibilità widget
cfg_home = settings.get_user_home_widgets_config(conn, user_email)
ordine = cfg_home["ordine"]
visibilita = cfg_home["visibilita"]

# Mappa metadati e descrizioni widget
WIDGET_INFO = {
    "calendario_settimanale": {
        "titolo": "Calendario Presenze Settimanale",
        "desc": "Panoramica presenze e ferie dei colleghi (settimana corrente e successiva).",
    },
    "aree_operative": {
        "titolo": "Aree Operative",
        "desc": "Scorciatoie di navigazione rapida ai moduli (Analisi Dati, Catalogo, Foto, Ferie).",
    },
    "stato_db": {
        "titolo": "Stato Database & Dati",
        "desc": "Metriche di sintesi su articoli, marchi e copertura temporale del database.",
    },
}

# Intestazione con pulsante di configurazione ordine e visibilità widget
c_sub, c_pop = st.columns([4, 1])
with c_sub:
    st.caption("Piattaforma direzionale ed operativa per l'analisi e la gestione aziendale.")
with c_pop:
    with st.popover("⚙️ Personalizza Widget", use_container_width=True):
        st.markdown("#### Personalizza Homepage")
        st.caption("Configura la visibilità e la posizione (1 = in alto, 2 = centrale, 3 = in basso):")
        with st.form("form_personalizza_widgets"):
            posizioni_scelte = {}
            visibilita_scelte = {}

            # Mostra i widget nell'ordine attuale con relativo selettore di posizione
            for idx, wid in enumerate(ordine):
                info_w = WIDGET_INFO.get(wid, {"titolo": wid, "desc": ""})
                col_v, col_p = st.columns([3, 2])
                with col_v:
                    visibilita_scelte[wid] = st.checkbox(
                        info_w["titolo"],
                        value=visibilita.get(wid, True),
                        key=f"home_vis_{wid}",
                        help=info_w["desc"],
                    )
                with col_p:
                    posizioni_scelte[wid] = st.selectbox(
                        "Posizione",
                        options=[1, 2, 3],
                        index=idx,
                        key=f"home_pos_{wid}",
                        help=f"Posizione per {info_w['titolo']}",
                    )

            salva_btn = st.form_submit_button("Salva Configurazione", type="primary", use_container_width=True)
            if salva_btn:
                # Riordina in base alla posizione scelta dall'utente (stabile)
                nuovo_ordine = sorted(ordine, key=lambda w: (posizioni_scelte[w], ordine.index(w)))
                settings.save_user_home_widgets_config(conn, user_email, nuovo_ordine, visibilita_scelte)
                st.success("Configurazione homepage salvata!")
                st.rerun()


# ------------------------------------------------------------------ Funzioni Render Widget
def _render_calendario_settimanale():
    section("Calendario Presenze Settimanale")
    col_cal_info, col_cal_btn = st.columns([3, 1])
    with col_cal_info:
        st.caption("Panoramica presenze e permessi per le giornate lavorative (Lunedì–Venerdì, corrente e prossima settimana).")
    with col_cal_btn:
        try:
            st.page_link("pages/24_Ferie_Calendario.py", label="Calendario Mensile 🗓️", use_container_width=True)
        except Exception:
            pass

    df_storico = ferie.get_ferie_storico(conn)
    html_settimanale = ferie.build_calendario_settimanale_html(df_storico)
    st.html(html_settimanale)
    st.markdown(
        "<div style='display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color:#64748B; margin-top:8px;'>"
        "<span><b style='color:#0D9488;'>Bordo Teal:</b> Giorno odierno</span>"
        "<span><b style='color:#B45309;'>Giallo chiaro:</b> Festività italiana</span>"
        "<span><b style='color:#0F172A;'>🕐 Nome:</b> Permesso orario (entrata posticipata / uscita anticipata)</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.write("")


def _render_aree_operative():
    section("Aree Operative")
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("### Analisi Dati")
            st.caption("Reportistica commerciale, performance multicanale, comparativa Y2Y, sell-through e monitoraggio resi.")
            try:
                st.page_link("pages/01_Dashboard.py", label="Accedi ad Analisi Dati", icon=None)
            except Exception:
                pass

        with st.container(border=True):
            st.markdown("### Gestione Catalogo")
            st.caption("Controllo anagrafica articoli, variazioni di stagione, listini e perimetri commerciali.")
            try:
                st.page_link("pages/20_Catalogo_Panoramica.py", label="Accedi a Gestione Catalogo", icon=None)
            except Exception:
                pass

    with c2:
        with st.container(border=True):
            st.markdown("### Gestione Foto")
            st.caption("Archivio fotografico centralizzato, associazione asset per modello/colore e verifica coperture.")
            try:
                st.page_link("pages/22_Foto_Archivio.py", label="Accedi a Gestione Foto", icon=None)
            except Exception:
                pass

        with st.container(border=True):
            st.markdown("### Ferie & Presenze")
            st.caption("Pianificazione presenze del personale, consuntivo ferie, richieste e saldi aziendali.")
            try:
                st.page_link("pages/24_Ferie_Calendario.py", label="Accedi a Ferie", icon=None)
            except Exception:
                pass
    st.write("")


def _render_stato_db():
    section("Stato Database & Dati")
    stats = db.get_anagrafica_stats(conn)
    tot_sku13 = stats.get("totale_sku13", 0)
    tot_sku7 = stats.get("totale_sku7", 0)
    marchi_count = len(stats.get("per_brand", {}))
    bounds = db.get_data_bounds(conn)
    copertura = f"{bounds[0]} - {bounds[1]}" if bounds[0] and bounds[1] else "Non disponibile"

    metric_cards([
        {"label": "Articoli in Anagrafica", "value": it_num(tot_sku13)},
        {"label": "Modelli Base (SKU7)", "value": it_num(tot_sku7)},
        {"label": "Marchi a Catalogo", "value": it_num(marchi_count)},
        {"label": "Copertura Temporale DB", "value": copertura},
    ])
    st.write("")


RENDERERS = {
    "calendario_settimanale": _render_calendario_settimanale,
    "aree_operative": _render_aree_operative,
    "stato_db": _render_stato_db,
}

# ------------------------------------------------------------------ Render Widget in ordine personalizzato
qualcosa_visibile = False
for wid in ordine:
    if visibilita.get(wid, True) and wid in RENDERERS:
        qualcosa_visibile = True
        RENDERERS[wid]()

# ------------------------------------------------------------------ Stato Vuoto se nessun widget selezionato
if not qualcosa_visibile:
    st.info(
        "Nessun widget attivo nella tua Homepage. "
        "Usa il pulsante **'⚙️ Personalizza Widget'** in alto a destra per selezionare e ordinare le sezioni che desideri visualizzare."
    )
