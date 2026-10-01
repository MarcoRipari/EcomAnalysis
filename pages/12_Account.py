import streamlit as st
from streamlit.components.v1 import html as _iframe_html

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

# ------------------------------------------------------------------ fattori esistenti
st.subheader("Fattori 2FA registrati")
try:
    fattori = auth.list_factors(sess["access_token"])
except auth.AuthError as e:
    st.error(str(e))
    st.stop()

if not fattori:
    st.caption(
        "Nessun fattore attivo: questo account entra con la sola password. "
        "Si consiglia vivamente di attivare la 2FA qui sotto."
    )
else:
    st.table([
        {"Nome": f.get("friendly_name"), "Tipo": f.get("factor_type"),
         "Stato": f.get("status"), "ID": f.get("id")}
        for f in fattori
    ])

st.divider()

# ------------------------------------------------------------------ attivazione (enroll)
st.subheader("Attiva 2FA — QR code + secret")
st.caption(
    "Genera il QR, scansionalo con la tua app TOTP (Google Authenticator, 1Password, "
    "Aegis, …) oppure inserisci a mano il secret, poi conferma con un codice."
)

with st.form("enroll_form"):
    nome = st.text_input("Nome del fattore (libero, es. 'iPhone')", value="App TOTP")
    avvia = st.form_submit_button("1️⃣ Genera QR code e secret")

if avvia:
    try:
        fattore = auth.enroll_totp(sess["access_token"], nome or "App TOTP")
        st.session_state["_enroll"] = fattore
    except auth.AuthError as e:
        st.error(str(e))

enroll = st.session_state.get("_enroll")
if enroll:
    c1, c2 = st.columns([1, 2])
    with c1:
        if enroll["qr_code"]:
            _iframe_html(f'<img src="{enroll["qr_code"]}" width="220" alt="QR TOTP"/>',
                        height=260)
    with c2:
        st.markdown("**Secret** (inserimento manuale nell'app TOTP):")
        st.code(enroll["secret"], language=None)
        if enroll["uri"]:
            st.caption(f"URI otpauth: `{enroll['uri']}`")
    with st.form("verify_enroll_form"):
        code = st.text_input("2️⃣ Codice a 6 cifre generato dall'app",
                             max_chars=6, key="verify_enroll_code")
        conferma = st.form_submit_button("3️⃣ Conferma e attiva la 2FA", type="primary")
    if conferma:
        try:
            full = auth.confirm_enroll(sess, enroll["id"], code.strip().replace(" ", ""))
        except auth.AuthError as e:
            st.error(str(e))
        else:
            st.session_state.pop("_enroll", None)
            auth.remember_session(full)
            st.success("✅ 2FA attivata: dal prossimo login verrà chiesto anche il codice TOTP.")
            st.caption("La tabella fattori si aggiorna al prossimo caricamento della pagina.")

st.divider()

# ------------------------------------------------------------------ rimozione fattore
st.subheader("Rimuovi un fattore")
verificati = [f for f in fattori
              if f.get("status") == "verified" and f.get("factor_type") == "totp"]
if not verificati:
    st.caption("Nessun fattore verificato da rimuovere.")
else:
    opzioni = {f["id"]: f.get("friendly_name") or f["id"] for f in verificati}
    with st.form("unenroll_form"):
        scelto = st.selectbox("Fattore", list(opzioni.keys()),
                              format_func=lambda i: opzioni[i])
        rimuovi = st.form_submit_button("Rimuovi fattore")
    if rimuovi:
        try:
            auth.unenroll_factor(sess["access_token"], scelto)
        except auth.AuthError as e:
            st.error(str(e))
        else:
            st.session_state["auth"]["ha_fattori"] = False
            st.success("Fattore rimosso.")
            st.caption("La tabella si aggiorna al prossimo caricamento della pagina.")
