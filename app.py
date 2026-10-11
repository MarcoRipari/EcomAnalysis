"""
EcomAnalysis — guscio di navigazione (menu a gruppi espandibili) + cancello di accesso.

Il menu della sidebar NON è quello automatico di Streamlit: è definito qui in modo
dichiarativo (GRUPPI_MENU) e renderizzato con st.expander + st.page_link; il routing
vero è gestito da st.navigation con position="hidden" (il menu automatico resta nascosto).

Autenticazione: st.navigation viene registrata PRIMA del cancello, poi
auth.require_session(): senza una sessione valida (login Supabase + 2FA TOTP)
mostra la schermata di accesso e blocca tutto il resto (menù compreso).
La sessione sopravvive al refresh della pagina grazie al cookie col refresh token (v. core/auth.py).

Come aggiungere una voce futura:
1. crea il file della pagina (una pagina Streamlit qualsiasi, es. pages/13_Nuova.py);
2. qui sotto crea lo st.Page corrispondente;
3. aggiungilo al gruppo desiderato dentro GRUPPI_MENU.

Nessuna logica di business qui: le pagine leggono la pipeline da
st.session_state["pipeline"], generata nella pagina ⬆️ Carica Dati.
"""
import streamlit as st

from core import auth, topbar
from core.design_system import apply_theme

# ---------------------------------------------------------------------------------------
# Definizione delle pagine (l'ordine nel menu è dato da GRUPPI_MENU)
# ---------------------------------------------------------------------------------------
page_carica = st.Page("pages/00_Carica_Dati.py", title="Carica Dati", icon="⬆️")
page_dashboard = st.Page("pages/01_Dashboard.py", title="Dashboard", icon="📊", default=True)
page_y2y_generale = st.Page("pages/02_Y2Y_Generale.py", title="Y2Y Generale", icon="📈")
page_articoli_collezioni = st.Page("pages/03_Articoli_e_Collezioni.py", title="Articoli & Collezioni", icon="🌳")
page_canali_mkp = st.Page("pages/04_Canali_Marketplace.py", title="Canali & Marketplace", icon="🛍️")
page_nazioni = st.Page("pages/05_Nazioni.py", title="Nazioni & Geografia", icon="🌍")
page_analisi_resi = st.Page("pages/06_Analisi_Resi.py", title="Analisi Resi", icon="🔄")
page_trova_sku = st.Page("pages/07_Trova_SKU.py", title="Trova SKU", icon="🔎")
page_taglie = st.Page("pages/08_Taglie.py", title="Taglie per Brand", icon="👟")
page_sell_through = st.Page("pages/09_Sell_Through.py", title="Sell-Through", icon="📦")
page_export = st.Page("pages/10_Export_Dati.py", title="Export Dati", icon="📤")
page_correzioni = st.Page("pages/13_Correzioni_DB.py", title="Correzioni DB", icon="🛠️")
page_log_riconciliazione = st.Page("pages/11_Log_Riconciliazione.py", title="Log Riconciliazione", icon="🔍")
page_account = st.Page("pages/12_Account.py", title="Account e 2FA", icon="🔐")

SUB = "sub"  # voce non cliccabile: semplice sottotitolo visivo dentro un gruppo


# ---------------------------------------------------------------------------------------
# Struttura del menu — un dizionario per ogni gruppo espandibile della sidebar.
# "voci": lista di pagine (st.Page) oppure (SUB, "Titolo") per un sottotitolo.
# Per un gruppo futuro basta aggiungere un dizionario con la stessa struttura.
# ---------------------------------------------------------------------------------------
GRUPPI_MENU = [
    {
        "titolo": "📊 Sintesi",
        "espanso": True,
        "voci": [
            page_dashboard,
            page_y2y_generale,
        ],
    },
    {
        "titolo": "📈 Performance",
        "espanso": True,
        "voci": [
            page_canali_mkp,
            page_nazioni,
            page_articoli_collezioni,
        ],
    },
    {
        "titolo": "👟 Prodotto & Resi",
        "espanso": True,
        "voci": [
            page_trova_sku,
            page_analisi_resi,
            page_taglie,
            page_sell_through,
        ],
    },
    {
        "titolo": "⚙️ Export & Sistema",
        "espanso": False,
        "voci": [
            page_carica,
            page_export,
            page_correzioni,
            page_log_riconciliazione,
            page_account,
        ],
    },
]

_pagine = [voce for gruppo in GRUPPI_MENU for voce in gruppo["voci"] if not isinstance(voce, tuple)]

# La navigazione va registrata PRIMA del cancello: se require_session() ferma l'app
# con st.stop() senza che st.navigation sia mai stato chiamato, Streamlit sostituisce
# il menù con quello automatico "piatto" (le pagine trovate in pages/, non compresse).
pg = st.navigation(_pagine, position="hidden")

# ---------------------------------------------------------------------------------------
# Cancello di accesso (login + 2FA + sessione persistente) — blocca qui se non autenticati
# ---------------------------------------------------------------------------------------
sess = auth.require_session()

# ---------------------------------------------------------------------------------------
# Sidebar: menu a gruppi espandibili + stato della pipeline + utente
# ---------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🧭 Menu")
    for gruppo in GRUPPI_MENU:
        with st.expander(gruppo["titolo"], expanded=gruppo["espanso"]):
            for voce in gruppo["voci"]:
                if isinstance(voce, tuple):
                    st.markdown(f"**{voce[1]}**")
                else:
                    st.page_link(voce, width="stretch")

    st.divider()
    st.caption(
        f"👤 **{sess['user'].get('email', 'utente')}** · sessione "
        f"{auth.DURATA_SESSIONE_GIORNI} giorni"
    )
    if st.button("🚪 Esci", width="stretch"):
        auth.logout(sess)   # revoca il refresh token su Supabase
        st.rerun()          # torna SUBITO alla schermata di login, come al primo accesso

apply_theme()   # CSS del tema valido anche per la barra periodo e per le pagine senza page_setup

# Barra periodo: sempre in alto, su ogni pagina (costruisce st.session_state["pipeline"])
topbar.render()

pg.run()
