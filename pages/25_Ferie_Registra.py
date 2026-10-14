from datetime import date, datetime
import pandas as pd
import streamlit as st

from core import db, ferie, roles
from core.design_system import page_setup

page_setup("Registra Ferie & Permessi", None)

conn = db.connect()
ferie.init_ferie_tables(conn)

user_email = st.session_state.get("user_email")
if not user_email:
    sess = st.session_state.get("auth", {}).get("user", {}) or {}
    user_email = sess.get("email", "")

user_role = st.session_state.get("user_role")
if not user_role:
    user_role = roles.get_user_role(conn, user_email)

is_admin = (user_role == "Admin")

df_dipendenti = ferie.get_dipendenti(conn, solo_attivi=True)
if df_dipendenti.empty:
    st.info("Nessun dipendente registrato nel sistema. Configura l'anagrafica in 'Configurazioni' -> 'Gestione Dipendenti'.")
    st.stop()

nomi = df_dipendenti["nome"].tolist()

# Pre-selezione / verifica del dipendente
email_clean = (user_email or "").strip().lower()
dip_trovato = None
if email_clean and not df_dipendenti.empty:
    corrisp = df_dipendenti[df_dipendenti["email"].str.lower() == email_clean]
    if not corrisp.empty:
        dip_trovato = corrisp.iloc[0]["nome"]
    else:
        nome_presunto = ferie.nome_da_email(email_clean)
        match_p = df_dipendenti[df_dipendenti["nome"].str.lower() == nome_presunto.lower()]
        if not match_p.empty:
            dip_trovato = match_p.iloc[0]["nome"]

if not is_admin and dip_trovato is None:
    st.warning(
        f"Nessuna posizione dipendente attiva associata alla tua utenza ({user_email}). "
        "Contatta un amministratore per configurare la tua anagrafica prima di registrare ferie o permessi."
    )
    st.stop()

default_index = nomi.index(dip_trovato) if dip_trovato in nomi else 0

# Selettore Dipendente e Tipologia Inserimento
c_dip, c_mod = st.columns([1, 1])
with c_dip:
    if is_admin:
        nome_selezionato = st.selectbox(
            "Dipendente",
            options=nomi,
            index=default_index,
            key="reg_nome_dipendente"
        )
    else:
        nome_selezionato = dip_trovato
        st.text_input("Dipendente", value=nome_selezionato, disabled=True)

with c_mod:
    modalita = st.radio(
        "Tipologia Inserimento",
        ["Giorno intero", "Permesso orario (entrata/uscita)"],
        horizontal=True,
        key="reg_modalita_ins",
    )

riga_dip = df_dipendenti[df_dipendenti["nome"] == nome_selezionato].iloc[0]
orario_dip = ferie.get_orario_dipendente(riga_dip)

st.divider()

if modalita == "Giorno intero":
    st.markdown("#### Registrazione Ferie a Giornata Intera")
    c1, c2 = st.columns(2)
    with c1:
        d_inizio = st.date_input("Data Inizio", format="DD/MM/YYYY", key="reg_d_inizio")
    with c2:
        d_fine = st.date_input("Data Fine", format="DD/MM/YYYY", key="reg_d_fine")

    col_tipo, col_note = st.columns([1, 2])
    with col_tipo:
        tipo_assenza = st.selectbox("Tipologia Assenza", ["Ferie", "Rettifica", "Altro"], key="reg_tipo_assenza")
    with col_note:
        note_assenza = st.text_input("Note (facoltative)", key="reg_note_assenza")

    if d_inizio <= d_fine:
        gg_lav = ferie.calcola_giorni_lavorativi_esatti(d_inizio, d_fine)
        st.caption(f"Giorni lavorativi effettivi calcolati: **{gg_lav} gg** (esclusi sabati, domeniche e festività nazionali).")

        sovrapposizioni = ferie.check_overlaps(conn, d_inizio, d_fine, escludi_nome=nome_selezionato)
        if sovrapposizioni:
            st.warning(f"Attenzione: Nelle stesse date risultano già assenti: **{', '.join(sovrapposizioni)}**")

    st.write("")
    if st.button("Registra Assenza", type="primary", use_container_width=False):
        if d_fine < d_inizio:
            st.error("La data di fine non può essere precedente alla data di inizio.")
        else:
            ok, msg = ferie.add_ferie(conn, nome_selezionato, d_inizio, d_fine, tipo_assenza, note=note_assenza)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

else:
    st.markdown("#### Registrazione Permesso Orario (Entrata Posticipata / Uscita Anticipata)")
    ore_standard = ferie.ore_giornaliere_previste(orario_dip)

    col_info, col_reset = st.columns([3, 1])
    with col_info:
        st.caption(
            f"Orario contrattuale per **{nome_selezionato}**: "
            f"**{orario_dip['mattina_inizio'].strftime('%H:%M')}–{orario_dip['mattina_fine'].strftime('%H:%M')}** / "
            f"**{orario_dip['pomeriggio_inizio'].strftime('%H:%M')}–{orario_dip['pomeriggio_fine'].strftime('%H:%M')}** "
            f"({ore_standard:g} ore/giorno)."
        )
    with col_reset:
        if st.button("🔄 Reimposta orari", help="Ripristina gli orari standard contrattuali", use_container_width=True):
            for k in [
                f"perm_ing_m_{nome_selezionato}",
                f"perm_usc_m_{nome_selezionato}",
                f"perm_ing_p_{nome_selezionato}",
                f"perm_usc_p_{nome_selezionato}",
                f"perm_ass_m_{nome_selezionato}",
                f"perm_ass_p_{nome_selezionato}",
            ]:
                st.session_state.pop(k, None)
            st.rerun()

    d_permesso = st.date_input("Data Permesso", format="DD/MM/YYYY", key=f"perm_data_{nome_selezionato}")

    c_mat, c_pom = st.columns(2)
    with c_mat:
        with st.container(border=True):
            st.markdown("**Mattina**")
            assente_m = st.checkbox("Assente tutta la mattina", key=f"perm_ass_m_{nome_selezionato}")
            if not assente_m:
                ing_m = st.time_input("Ingresso mattina", value=orario_dip["mattina_inizio"], key=f"perm_ing_m_{nome_selezionato}")
                usc_m = st.time_input("Uscita mattina", value=orario_dip["mattina_fine"], key=f"perm_usc_m_{nome_selezionato}")
            else:
                ing_m = orario_dip["mattina_inizio"]
                usc_m = orario_dip["mattina_inizio"]

    with c_pom:
        with st.container(border=True):
            st.markdown("**Pomeriggio**")
            assente_p = st.checkbox("Assente tutto il pomeriggio", key=f"perm_ass_p_{nome_selezionato}")
            if not assente_p:
                ing_p = st.time_input("Ingresso pomeriggio", value=orario_dip["pomeriggio_inizio"], key=f"perm_ing_p_{nome_selezionato}")
                usc_p = st.time_input("Uscita pomeriggio", value=orario_dip["pomeriggio_fine"], key=f"perm_usc_p_{nome_selezionato}")
            else:
                ing_p = orario_dip["pomeriggio_inizio"]
                usc_p = orario_dip["pomeriggio_inizio"]

    note_perm = st.text_input("Note (facoltative)", key=f"perm_note_{nome_selezionato}")

    frazione = ferie.calcola_giorni_da_permesso_orario(
        orario_dip, assente_m, ing_m, usc_m, assente_p, ing_p, usc_p
    )
    desc_anteprima = ferie.descrivi_permesso_orario(
        orario_dip, assente_m, ing_m, usc_m, assente_p, ing_p, usc_p
    )

    if frazione > 0:
        st.info(f"Verranno scalati **{frazione:g} giorni** dal monte ferie ({desc_anteprima}).")
    else:
        st.caption(f"Riepilogo ore compensato (0 giorni scalati): {desc_anteprima}.")

    st.write("")
    if st.button("Registra Permesso Orario", type="primary", use_container_width=False):
        ok, msg = ferie.add_permesso_orario(
            conn, nome_selezionato, d_permesso, orario_dip,
            assente_m, ing_m, usc_m, assente_p, ing_p, usc_p,
            note=note_perm
        )
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)
