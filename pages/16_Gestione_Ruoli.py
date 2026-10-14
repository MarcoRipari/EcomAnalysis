import streamlit as st

from core import db, roles
from core.design_system import page_setup, section, data_table, empty_state

page_setup("Gestione Ruoli & Permessi", None)

conn = db.connect()
roles.init_roles(conn)

current_user_role = st.session_state.get("user_role", "Admin")
if current_user_role != "Admin":
    st.error("Accesso riservato agli amministratori.")
    st.stop()

tab_permessi, tab_utenti, tab_ruoli = st.tabs([
    "Matrice Permessi",
    "Assegnazione Utenti",
    "Configurazione Ruoli",
])

# ---------------------------------------------------------------------------------------
# TAB 1: MATRICE PERMESSI PER RUOLO
# ---------------------------------------------------------------------------------------
with tab_permessi:
    section("Permessi per Profilo di Ruolo")
    tutti_ruoli = roles.get_all_roles(conn)
    nomi_ruoli = [r["nome"] for r in tutti_ruoli]

    ruolo_scelto = st.selectbox("Seleziona Ruolo da Configurare", nomi_ruoli, index=1 if len(nomi_ruoli) > 1 else 0)

    if ruolo_scelto == "Admin":
        st.info("Il ruolo **Admin** dispone di accesso completo e irrevocabile a tutte le macro-aree e pagine del sistema.")
    else:
        permessi_attuali = roles.get_role_permissions(conn, ruolo_scelto)
        gruppi = roles.get_groups_metadata()

        st.caption(f"Configura le pagine e i moduli visibili per il ruolo **{ruolo_scelto}**:")

        with st.form(f"form_permessi_{ruolo_scelto}"):
            nuove_selezioni = []
            for nome_gruppo, pagine in gruppi.items():
                st.markdown(f"#### {nome_gruppo}")
                cols = st.columns(min(len(pagine), 3) or 1)
                for idx, p in enumerate(pagine):
                    col = cols[idx % len(cols)]
                    attivo_default = p["id"] in permessi_attuali
                    chk = col.checkbox(
                        p["titolo"],
                        value=attivo_default,
                        key=f"chk_{ruolo_scelto}_{p['id']}",
                        help=f"ID: {p['id']}",
                    )
                    if chk:
                        nuove_selezioni.append(p["id"])
                st.divider()

            salva = st.form_submit_button("Salva Permessi Ruolo", type="primary")

        if salva:
            ok, msg = roles.set_role_permissions(conn, ruolo_scelto, nuove_selezioni)
            if ok:
                st.success(f"Permessi per '{ruolo_scelto}' salvati con successo ({len(nuove_selezioni)} pagine abilitate).")
                # Se l'utente corrente ha questo ruolo, aggiorna i permessi in sessione
                if st.session_state.get("user_role") == ruolo_scelto:
                    st.session_state["user_permissions"] = set(nuove_selezioni)
                st.rerun()
            else:
                st.error(msg)

# ---------------------------------------------------------------------------------------
# TAB 2: UTENTI & ASSEGNAZIONE RUOLI
# ---------------------------------------------------------------------------------------
with tab_utenti:
    section("Utenti Registrati e Ruoli Attivi")
    utenti = roles.get_all_users(conn)

    if utenti:
        import pandas as pd
        df_utenti = pd.DataFrame(utenti)
        df_utenti.columns = ["Email", "Ruolo", "Data Assegnazione"]
        data_table(df_utenti)
    else:
        empty_state("Nessun utente esplicitamente censito. Il primo accesso configurerà l'utente come Admin.")

    st.divider()

    c_ass, c_rim = st.columns(2)

    with c_ass:
        st.markdown("#### Assegna o Modifica Ruolo Utente")
        with st.form("form_assegna_utente"):
            email_input = st.text_input("Email Utente", placeholder="es. mario.rossi@azienda.com")
            ruolo_select = st.selectbox("Ruolo da Assegnare", [r["nome"] for r in tutti_ruoli])
            btn_assegna = st.form_submit_button("Assegna Ruolo", type="primary")

        if btn_assegna:
            if not email_input.strip():
                st.error("Inserisci un indirizzo email valido.")
            else:
                ok, msg = roles.set_user_role(conn, email_input.strip(), ruolo_select)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with c_rim:
        st.markdown("#### Rimuovi Assegnazione Utente")
        if utenti:
            with st.form("form_rimuovi_utente"):
                email_da_rimuovere = st.selectbox("Seleziona Utente da Rimuovere", [u["email"] for u in utenti])
                btn_rimuovi = st.form_submit_button("Rimuovi Assegnazione", type="secondary")

            if btn_rimuovi:
                ok, msg = roles.delete_user_role(conn, email_da_rimuovere)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.caption("Nessun utente rimovibile al momento.")

# ---------------------------------------------------------------------------------------
# TAB 3: CONFIGURAZIONE NUOVI RUOLI
# ---------------------------------------------------------------------------------------
with tab_ruoli:
    section("Ruoli Aziendali")
    import pandas as pd

    df_ruoli = pd.DataFrame([
        {
            "Ruolo": r["nome"],
            "Descrizione": r["descrizione"],
            "Tipo": "Sistema (Protetto)" if r["is_system"] else "Personalizzato",
            "Data Creazione": r["creato_il"],
        }
        for r in tutti_ruoli
    ])
    data_table(df_ruoli)

    st.divider()

    c_crea, c_del = st.columns(2)

    with c_crea:
        st.markdown("#### Crea Nuovo Ruolo")
        with st.form("form_crea_ruolo"):
            nuovo_nome = st.text_input("Nome Ruolo (es. Commerciale, HR, StoreManager)")
            nuova_desc = st.text_input("Descrizione", placeholder="es. Accesso ad analisi vendite e resi")
            btn_crea = st.form_submit_button("Crea Ruolo", type="primary")

        if btn_crea:
            ok, msg = roles.create_role(conn, nuovo_nome, nuova_desc)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    with c_del:
        st.markdown("#### Elimina Ruolo Personalizzato")
        ruoli_eliminabili = [r["nome"] for r in tutti_ruoli if not r["is_system"]]
        if ruoli_eliminabili:
            with st.form("form_elimina_ruolo"):
                ruolo_da_eliminare = st.selectbox("Seleziona Ruolo da Eliminare", ruoli_eliminabili)
                btn_elimina = st.form_submit_button("Elimina Ruolo", type="secondary")

            if btn_elimina:
                ok, msg = roles.delete_role(conn, ruolo_da_eliminare)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.caption("Nessun ruolo personalizzato eliminabile (i ruoli di sistema sono protetti).")
