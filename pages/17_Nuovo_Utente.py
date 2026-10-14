import secrets
import pandas as pd
import streamlit as st

from core import auth, db, roles, ferie
from core.design_system import page_setup, section, data_table, empty_state

page_setup("Crea Nuovo Utente", None)

conn = db.connect()
roles.init_roles(conn)

current_user_role = st.session_state.get("user_role", "Admin")
if current_user_role != "Admin":
    st.error("Accesso riservato agli amministratori.")
    st.stop()

tutti_ruoli = roles.get_all_roles(conn)
nomi_ruoli = [r["nome"] for r in tutti_ruoli]

col_form, col_lista = st.columns([1.1, 0.9])

with col_form:
    section("Dati Nuovo Utente")
    st.caption("Crea un account aziendale in Supabase Auth e assegna il profilo di ruolo per l'accesso ai moduli.")

    with st.form("form_crea_nuovo_utente"):
        email = st.text_input("Email Aziendale", placeholder="es. mario.rossi@azienda.com")
        ruolo = st.selectbox("Ruolo di Accesso", nomi_ruoli, index=1 if "Finance" in nomi_ruoli else 0)

        tipo_pwd = st.radio("Modalità Password", ["Genera password casuale sicura", "Inserisci password manualmente"], horizontal=True)

        if tipo_pwd == "Genera password casuale sicura":
            pwd_autogen = st.session_state.get("_pwd_suggerita")
            if not pwd_autogen:
                pwd_autogen = secrets.token_urlsafe(12)
                st.session_state["_pwd_suggerita"] = pwd_autogen
            st.text_input("Password Generata (modificabile)", value=pwd_autogen, key="input_pwd_gen")
            password_scelta = st.session_state.get("input_pwd_gen", pwd_autogen)
        else:
            pwd_manuale = st.text_input("Password Iniziale", type="password", key="pwd_manuale")
            pwd_conferma = st.text_input("Conferma Password", type="password", key="pwd_conferma")
            password_scelta = pwd_manuale

        nome_referente = st.text_input("Nome e Cognome / Riferimento (opzionale)", placeholder="es. Mario Rossi")

        crea = st.form_submit_button("Crea e Registra Utente", type="primary")

    if crea:
        email_clean = (email or "").strip().lower()
        if not email_clean or "@" not in email_clean or "." not in email_clean:
            st.error("Inserisci un indirizzo email aziendale valido.")
        elif tipo_pwd == "Inserisci password manualmente" and (len(password_scelta) < 8 or password_scelta != pwd_conferma):
            if len(password_scelta) < 8:
                st.error("La password deve contenere almeno 8 caratteri.")
            else:
                st.error("Le password inserite non coincidono.")
        else:
            try:
                # 1. Registra su Supabase Auth
                meta = {"nome": nome_referente.strip(), "ruolo": ruolo}
                auth.sign_up_user(email_clean, password_scelta, metadata=meta)

                # 2. Registra ruolo nel database SQLite locale
                roles.set_user_role(conn, email_clean, ruolo)

                # 3. Registra automaticamente l'utente come dipendente nell'anagrafica ferie
                nome_dipendente = (nome_referente or "").strip() or ferie.nome_da_email(email_clean)
                ferie.add_dipendente(conn, nome_dipendente, email=email_clean, totale_annuo=26.0)

                st.session_state.pop("_pwd_suggerita", None)
                st.success(f"Utente **{email_clean}** creato con successo e configurato con ruolo **{ruolo}**.")

                st.info(
                    f"**Riepilogo Credenziali da comunicare all'utente:**\n\n"
                    f"- **Email**: `{email_clean}`\n"
                    f"- **Password temporanea**: `{password_scelta}`\n\n"
                    f"Al primo accesso l'utente effettuerà il login con queste credenziali e verrà guidato "
                    f"automaticamente nella configurazione del secondo fattore di autenticazione obbligatorio (2FA TOTP)."
                )
            except auth.AuthError as err:
                st.error(str(err))
            except Exception as exc:
                st.error(f"Errore durante la registrazione: {exc}")

with col_lista:
    section("Utenti e Profili Attivi")
    utenti = roles.get_all_users(conn)

    if utenti:
        df_utenti = pd.DataFrame(utenti)
        df_utenti.columns = ["Email", "Ruolo", "Assegnato il"]
        data_table(df_utenti)
    else:
        empty_state("Nessun utente registrato nel database.")

    st.divider()
    st.markdown("#### Note di Sicurezza")
    st.caption(
        "Tutti gli utenti registrati sono soggetti al cancello di autenticazione con **password + secondo fattore TOTP (2FA)**. "
        "I permessi e la visibilità delle pagine associate al ruolo possono essere personalizzati nella pagina "
        "**Export & Sistema → Gestione Ruoli & Permessi**."
    )
