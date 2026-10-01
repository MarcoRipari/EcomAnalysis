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

from core import auth

# ---------------------------------------------------------------------------------------
# Definizione delle pagine (l'ordine nel menu è dato da GRUPPI_MENU)
# ---------------------------------------------------------------------------------------
page_carica = st.Page("pages/00_Carica_Dati.py", title="Carica Dati", icon="⬆️", default=True)
page_dashboard = st.Page("pages/01_Dashboard.py", title="Dashboard", icon="📊")
page_y2y_generale = st.Page("pages/02_Y2Y_Generale.py", title="Y2Y Generale", icon="📈")
page_y2y_collezioni = st.Page("pages/03_Y2Y_Collezioni.py", title="Y2Y Collezioni", icon="🌳")
page_y2y_codici = st.Page("pages/04_Y2Y_Codici.py", title="Y2Y Codici", icon="🔢")
page_carryover = st.Page("pages/05_Carryover.py", title="Carryover", icon="♻️")
page_taglie = st.Page("pages/06_Taglie.py", title="Taglie per Brand", icon="👟")
page_analisi_resi = st.Page("pages/07_Analisi_Resi.py", title="Analisi Resi", icon="🔄")
page_log_riconciliazione = st.Page("pages/08_Log_Riconciliazione.py", title="Log Riconciliazione", icon="🔍")
page_sell_through = st.Page("pages/09_Sell_Through.py", title="Sell-Through", icon="📦")
page_nazioni = st.Page("pages/10_Nazioni.py", title="Nazioni", icon="🌍")
page_report_unificato = st.Page("pages/11_Report_Unificato.py", title="Report Unificato", icon="🧾")
page_account = st.Page("pages/12_Account.py", title="Account e 2FA", icon="🔐")

SUB = "sub"  # voce non cliccabile: semplice sottotitolo visivo dentro un gruppo


# ---------------------------------------------------------------------------------------
# Struttura del menu — un dizionario per ogni gruppo espandibile della sidebar.
# "voci": lista di pagine (st.Page) oppure (SUB, "Titolo") per un sottotitolo.
# Per un gruppo futuro basta aggiungere un dizionario con la stessa struttura.
# ---------------------------------------------------------------------------------------
GRUPPI_MENU = [
    {
        "titolo": "📂 Analisi Dati",
        "espanso": True,
        "voci": [
            page_carica,
            page_dashboard,
            (SUB, "Report"),
            page_y2y_generale,
            page_y2y_collezioni,
            page_y2y_codici,
            page_carryover,
            page_taglie,
            page_analisi_resi,
            page_log_riconciliazione,
            page_sell_through,
            page_nazioni,
            page_report_unificato,
        ],
    },
    {
        "titolo": "⚙️ Account",
        "espanso": False,
        "voci": [page_account],
    },
    # Gruppi futuri: aggiungere qui altri dizionari con la stessa struttura.
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
                    st.page_link(voce, use_container_width=True)

    st.divider()
    pipe = st.session_state.get("pipeline")
    if pipe is None:
        st.caption("⚠️ Dati report **non generati**: scegli il periodo in **⬆️ Carica Dati**.")
    else:
        _a = st.session_state.get("periodo_a_label", "—")
        _b = st.session_state.get("periodo_b_label")
        _per = st.session_state.get("perimetro_label", "—")
        st.caption(
            f"✅ Dati pronti\n\n**Periodo**: {_a}"
            + (f"\n\n**Confronto**: {_b}" if _b else "")
            + f"\n\n**Perimetro**: {_per}"
        )

    st.divider()
    st.caption(
        f"👤 **{sess['user'].get('email', 'utente')}** · sessione "
        f"{auth.DURATA_SESSIONE_GIORNI} giorni"
    )
    if st.button("🚪 Esci", use_container_width=True):
        auth.logout(sess)   # revoca il refresh token su Supabase
        st.rerun()          # torna SUBITO alla schermata di login, come al primo accesso

pg.run()
