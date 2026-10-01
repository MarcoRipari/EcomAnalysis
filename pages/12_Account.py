import time

import streamlit as st

from core import auth

st.set_page_config(page_title="Account e 2FA", page_icon="🔐", layout="wide")
st.title("🔐 Account — gestione 2FA (TOTP)")

sess = st.session_state.get("auth")
if sess is None:
    st.info("Sessione non attiva: rifai l'accesso.")   # difensivo: via menù non capita
    st.stop()

st.success(f"Connesso come **{sess['user'].get('email', '?')}**")
st.caption(
    f"Livello di autenticazione attuale: **{sess['aal']}** (aal2 = password + secondo fattore). "
    f"Il login resta valido per **{auth.DURATA_SESSIONE_GIORNI} giorni** di inattività "
    "(cookie del browser + refresh token Supabase con rotazione automatica)."
)

st.divider()

# ------------------------------------------------------------------ fattore attivo
st.subheader("Fattore 2FA attivo")
try:
    fattori = [f for f in auth.list_factors(sess["access_token"])
               if f.get("factor_type") == "totp" and f.get("status") == "verified"]
except auth.AuthError as e:
    st.error(str(e))
    st.stop()

if not fattori:
    st.warning(
        "Nessun fattore TOTP attivo: al prossimo accesso l'app chiederà di attivarne uno."
    )
else:
    st.table([
        {"Nome": f.get("friendly_name"), "Creato il": f.get("created_at", "—"),
         "ID": f.get("id")}
        for f in fattori
    ])

st.divider()

# ------------------------------------------------------------------ sostituzione (cambio telefono)
st.subheader("Sostituisci il fattore (es. cambio telefono)")
st.caption(
    "Un solo fattore TOTP è più che sufficiente: il secret funziona su qualsiasi "
    "dispositivo/app. Qui lo rigeneri per il telefono nuovo — **il fattore attuale "
    "viene rimosso solo dopo che quello nuovo è verificato**, così non resti mai "
    "senza 2FA."
)

if st.button("1️⃣ Genera nuovo QR code e secret"):
    try:
        nome = f"App TOTP {time.strftime('%d/%m/%Y %H:%M:%S')}"
        st.session_state["_sostituisci"] = auth.enroll_totp(sess["access_token"], nome)
    except auth.AuthError as e:
        st.error(str(e))

nuovo = st.session_state.get("_sostituisci")
if nuovo:
    c1, c2 = st.columns([1, 2])
    with c1:
        auth.qr_component(nuovo["qr_code"])
    with c2:
        st.markdown("**Secret** (inserimento manuale nell'app TOTP):")
        st.code(nuovo["secret"], language=None)
        if nuovo.get("uri"):
            st.caption(f"URI otpauth: `{nuovo['uri']}`")
    with st.form("verify_sostituisci_form"):
        code = st.text_input("2️⃣ Codice a 6 cifre generato dalla NUOVA app",
                             max_chars=6, key="verify_sostituisci_code")
        conferma = st.form_submit_button("3️⃣ Conferma e sostituisci", type="primary")
    if conferma:
        try:
            full = auth.confirm_enroll(sess, nuovo["id"], code.strip().replace(" ", ""))
        except auth.AuthError as e:
            st.error(str(e))
        else:
            # rimuovi i vecchi fattori TOTP verificati: resta attivo solo quello nuovo
            for f in fattori:
                if f.get("id") != nuovo["id"]:
                    try:
                        auth.unenroll_factor(sess["access_token"], f["id"])
                    except auth.AuthError:
                        pass
            st.session_state.pop("_sostituisci", None)
            auth.remember_session(full)   # sessione aal2 nuova — niente st.rerun dopo
            st.success("✅ Fattore sostituito: dal telefono vecchio non si generano "
                       "più codici validi.")
            st.caption("La tabella si aggiorna al prossimo caricamento della pagina.")

st.divider()

# ------------------------------------------------------------------ cambio password
st.subheader("Cambia password")
with st.form("pwd_form"):
    nuova = st.text_input("Nuova password", type="password", key="pwd_nuova")
    ripeti = st.text_input("Ripeti la nuova password", type="password", key="pwd_ripeti")
    cambia = st.form_submit_button("Aggiorna password", type="primary")
if cambia:
    if len(nuova) < 8:
        st.error("La password deve avere almeno 8 caratteri.")
    elif nuova != ripeti:
        st.error("Le due password non coincidono.")
    else:
        try:
            auth.update_password(sess["access_token"], nuova)
        except auth.AuthError as e:
            st.error(str(e))
        else:
            st.success("✅ Password aggiornata: dalla prossima volta usala per accedere.")
