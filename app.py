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
import importlib
import streamlit as st

from core import auth, topbar, db, engine, roles, ferie, chatbot
importlib.reload(auth)
importlib.reload(topbar)
importlib.reload(db)
importlib.reload(engine)
importlib.reload(roles)
importlib.reload(ferie)
from core.design_system import apply_theme

# ---------------------------------------------------------------------------------------
# Definizione delle pagine (l'ordine nel menu è dato da GRUPPI_MENU)
# ---------------------------------------------------------------------------------------
page_home = st.Page("pages/00_Home.py", title="Homepage", icon=None, default=True)

# Analisi Dati
page_dashboard = st.Page("pages/01_Dashboard.py", title="Dashboard", icon=None)
page_y2y_generale = st.Page("pages/02_Y2Y_Generale.py", title="Y2Y Generale", icon=None)
page_canali_mkp = st.Page("pages/04_Canali_Marketplace.py", title="Canali & Marketplace", icon=None)
page_nazioni = st.Page("pages/05_Nazioni.py", title="Nazioni & Geografia", icon=None)
page_articoli_collezioni = st.Page("pages/03_Articoli_e_Collezioni.py", title="Articoli & Collezioni", icon=None)
page_analisi_resi = st.Page("pages/06_Analisi_Resi.py", title="Analisi Resi", icon=None)
page_trova_sku = st.Page("pages/07_Trova_SKU.py", title="Trova SKU", icon=None)
page_taglie = st.Page("pages/08_Taglie.py", title="Taglie per Brand", icon=None)
page_sell_through = st.Page("pages/09_Sell_Through.py", title="Sell-Through", icon=None)

# Gestione Catalogo
page_cat_panoramica = st.Page("pages/20_Catalogo_Panoramica.py", title="Panoramica Catalogo", icon=None)
page_cat_articoli = st.Page("pages/21_Catalogo_Articoli.py", title="Articoli & Listini", icon=None)

# Gestione Foto
page_foto_archivio = st.Page("pages/22_Foto_Archivio.py", title="Archivio Fotografico", icon=None)
page_foto_carica = st.Page("pages/23_Foto_Caricamento.py", title="Carica & Associa", icon=None)

# Ferie
page_ferie_calendario = st.Page("pages/24_Ferie_Calendario.py", title="Calendario", icon=None)
page_ferie_registra = st.Page("pages/25_Ferie_Registra.py", title="Registra Ferie & Permessi", icon=None)
page_ferie_riepilogo = st.Page("pages/26_Ferie_Riepilogo.py", title="Riepilogo", icon=None)
page_ferie_config = st.Page("pages/27_Ferie_Configurazioni.py", title="Configurazioni", icon=None)

# Export & Sistema
page_carica = st.Page("pages/00_Carica_Dati.py", title="Carica Dati", icon=None)
page_anagrafica = st.Page("pages/15_Anagrafica.py", title="Anagrafica Articoli", icon=None)
page_export = st.Page("pages/10_Export_Dati.py", title="Export Dati", icon=None)
page_configurazioni = st.Page("pages/14_Configurazioni.py", title="Configurazioni", icon=None)
page_correzioni = st.Page("pages/13_Correzioni_DB.py", title="Correzioni DB", icon=None)
page_log_riconciliazione = st.Page("pages/11_Log_Riconciliazione.py", title="Log Riconciliazione", icon=None)
page_account = st.Page("pages/12_Account.py", title="Account e Sicurezza", icon=None)
page_ruoli = st.Page("pages/16_Gestione_Ruoli.py", title="Gestione Ruoli & Permessi", icon=None)
page_nuovo_utente = st.Page("pages/17_Nuovo_Utente.py", title="Crea Nuovo Utente", icon=None)
page_stato_connessioni = st.Page("pages/18_Stato_Connessioni.py", title="Stato Connessioni", icon=None)

# Pagina TEST (fuori da tutti i gruppi menu, in fondo a tutto, solo per Admin)
page_test_chat = st.Page("pages/99_Test_Chatbot.py", title="TEST Chatbot", icon=None)

PAGE_TO_ID = {
    page_home: "00_Home",
    page_dashboard: "01_Dashboard",
    page_y2y_generale: "02_Y2Y_Generale",
    page_canali_mkp: "04_Canali_Marketplace",
    page_nazioni: "05_Nazioni",
    page_articoli_collezioni: "03_Articoli_e_Collezioni",
    page_analisi_resi: "06_Analisi_Resi",
    page_trova_sku: "07_Trova_SKU",
    page_taglie: "08_Taglie",
    page_sell_through: "09_Sell_Through",
    page_cat_panoramica: "20_Catalogo_Panoramica",
    page_cat_articoli: "21_Catalogo_Articoli",
    page_foto_archivio: "22_Foto_Archivio",
    page_foto_carica: "23_Foto_Caricamento",
    page_ferie_calendario: "24_Ferie_Calendario",
    page_ferie_registra: "25_Ferie_Registra",
    page_ferie_riepilogo: "26_Ferie_Riepilogo",
    page_ferie_config: "27_Ferie_Configurazioni",
    page_carica: "00_Carica_Dati",
    page_anagrafica: "15_Anagrafica",
    page_export: "10_Export_Dati",
    page_configurazioni: "14_Configurazioni",
    page_correzioni: "13_Correzioni_DB",
    page_log_riconciliazione: "11_Log_Riconciliazione",
    page_stato_connessioni: "18_Stato_Connessioni",
    page_account: "12_Account",
    page_ruoli: "16_Gestione_Ruoli",
    page_nuovo_utente: "17_Nuovo_Utente",
    page_test_chat: "99_Test_Chatbot",
}

SUB = "sub"  # voce non cliccabile: semplice sottotitolo visivo dentro un gruppo


# ---------------------------------------------------------------------------------------
# Struttura dei gruppi espandibili della sidebar.
# La Homepage è ora una voce autonoma diretta in cima al menu (non espandibile).
# ---------------------------------------------------------------------------------------
GRUPPI_MENU = [
    {
        "titolo": "Analisi Dati",
        "espanso": False,
        "voci": [
            page_dashboard,
            page_y2y_generale,
            page_canali_mkp,
            page_nazioni,
            page_articoli_collezioni,
            page_analisi_resi,
            page_trova_sku,
            page_taglie,
            page_sell_through,
        ],
    },
    {
        "titolo": "Gestione Catalogo",
        "espanso": False,
        "voci": [
            page_cat_panoramica,
            page_cat_articoli,
        ],
    },
    {
        "titolo": "Gestione Foto",
        "espanso": False,
        "voci": [
            page_foto_archivio,
            page_foto_carica,
        ],
    },
    {
        "titolo": "Ferie",
        "espanso": False,
        "voci": [
            page_ferie_calendario,
            page_ferie_riepilogo,
            page_ferie_registra,
            page_ferie_config,
        ],
    },
    {
        "titolo": "Export & Sistema",
        "espanso": False,
        "voci": [
            page_carica,
            page_anagrafica,
            page_export,
            page_configurazioni,
            page_correzioni,
            page_log_riconciliazione,
            page_stato_connessioni,
            page_account,
            page_ruoli,
            page_nuovo_utente,
        ],
    },
]

_pagine = (
    [page_home]
    + [voce for gruppo in GRUPPI_MENU for voce in gruppo["voci"] if not isinstance(voce, tuple)]
    + [page_test_chat]
)

# La navigazione va registrata PRIMA del cancello
pg = st.navigation(_pagine, position="hidden")

# ---------------------------------------------------------------------------------------
# Cancello di accesso (login + 2FA + sessione persistente) — blocca qui se non autenticati
# ---------------------------------------------------------------------------------------
sess = auth.require_session()

# Inizializzazione ruoli e determinazione permessi utente
conn = db.connect()
roles.init_roles(conn)
ferie.init_ferie_tables(conn)
chatbot.init_chatbot_tables(conn)
user_email = sess["user"].get("email", "") if sess and "user" in sess else ""
user_role = roles.get_user_role(conn, user_email)
user_permissions = roles.get_role_permissions(conn, user_role)

st.session_state["user_role"] = user_role
st.session_state["user_email"] = user_email
st.session_state["user_permissions"] = user_permissions

# ---------------------------------------------------------------------------------------
# Sidebar: voce Homepage + menu a gruppi espandibili (filtrati per ruolo) + pagina TEST + utente
# ---------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Menu")

    # Homepage: voce singola diretta, non espandibile
    if "00_Home" in user_permissions:
        st.page_link(page_home, width="stretch")
        st.markdown("<div style='margin-bottom: 6px;'></div>", unsafe_allow_html=True)

    for gruppo in GRUPPI_MENU:
        # Mostra solo le pagine permesse per il ruolo
        voci_visibili = [
            voce for voce in gruppo["voci"]
            if isinstance(voce, tuple) or PAGE_TO_ID.get(voce) in user_permissions
        ]
        if not voci_visibili:
            continue
        with st.expander(gruppo["titolo"], expanded=gruppo["espanso"]):
            for voce in voci_visibili:
                if isinstance(voce, tuple):
                    st.markdown(f"**{voce[1]}**")
                else:
                    st.page_link(voce, width="stretch")

    # Pagina TEST: fuori da tutti i menu, in fondo a tutto, disponibile solo per admin
    if user_role == "Admin" and "99_Test_Chatbot" in user_permissions:
        st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
        st.page_link(page_test_chat, width="stretch")

    st.divider()
    st.caption(
        f"**{user_email or 'utente'}** ({user_role}) · sessione "
        f"{auth.DURATA_SESSIONE_GIORNI} giorni"
    )
    if st.button("Esci", width="stretch"):
        auth.logout(sess)   # revoca il refresh token su Supabase
        st.rerun()          # torna SUBITO alla schermata di login, come al primo accesso

apply_theme()   # CSS del tema valido anche per la barra periodo e per le pagine senza page_setup

# Controllo accessi sulla pagina richiesta: blocco se non autorizzata per il ruolo
active_id = PAGE_TO_ID.get(pg)
if active_id and active_id not in user_permissions:
    st.error("Accesso Negato: il ruolo corrente non dispone dei permessi per visualizzare questa pagina.")
    st.stop()

PAGINE_ANALISI_DATI = {
    "01_Dashboard", "02_Y2Y_Generale", "04_Canali_Marketplace",
    "05_Nazioni", "03_Articoli_e_Collezioni", "06_Analisi_Resi",
    "07_Trova_SKU", "08_Taglie", "09_Sell_Through"
}

# Spaziatura dinamica e barra periodo: riserva spazio superiore solo per pagine Analisi Dati con topbar
if active_id in PAGINE_ANALISI_DATI:
    st.markdown("<style>.block-container, [data-testid='stMainBlockContainer'] { padding-top: 3.25rem !important; }</style>", unsafe_allow_html=True)
    topbar.render()
else:
    st.markdown("<style>.block-container, [data-testid='stMainBlockContainer'] { padding-top: 1.25rem !important; }</style>", unsafe_allow_html=True)

pg.run()
