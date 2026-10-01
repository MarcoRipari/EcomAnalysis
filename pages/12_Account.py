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
        {"Nome": f.get("friendly_name"),
         "Creato il": auth.fmt_data(f.get("created_at", "")),
         "ID": f.get("id")}
        for f in fattori
    ])

st.divider()

# ------------------------------------------------------------------ sostituzione (cambio telefono)
st.subheader("Sostituisci il fattore (es. cambio telefono)")
st.caption(
    "Un solo fattore TOTP è più che sufficiente: il secret funziona su qualsiasi "
    "dispositivo/app. Qui lo rigeneri per il telefono nuovo. **Premendo “Genera” il "
    "fattore attuale viene rimosso subito** (GoTrue non permette due fattori con lo "
    "stesso nome): conferma poi il codice della NUOVA app, altrimenti al prossimo "
    "accesso l'app ti chiederà di riattivare la 2FA."
)

if st.button("1️⃣ Genera nuovo QR code e secret"):
    try:
        auth.pulisci_fattori(sess["access_token"])   # rimuove il fattore attuale (stesso nome)
        st.session_state["_sostituisci"] = auth.enroll_totp(sess["access_token"], "Accesso 2FA")
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


st.divider()

# ------------------------------------------------------------------ chiavi API (fase 3)
import hashlib
import secrets as _secrets
from datetime import datetime, timezone

import requests as _rq

st.subheader("🔑 Chiavi API — accesso esterno ai dati")
st.caption(
    "Una chiave API permette a Excel, Power BI, script o applicazioni di terze parti di "
    "scaricare i dati dall'API di EcomAnalysis (https://TUODOMINIO/api/v1/…). "
    "La chiave viene mostrata **solo alla creazione**: copiala e conservala subito. "
    "Puoi revocarla quando vuoi (effetto entro 5 minuti). Pratica consigliata: "
    "una chiave per strumento, così puoi revocarle separatamente."
)


def _api_supa_url() -> str:
    return str(st.secrets.get("SUPABASE_URL") or "").rstrip("/")


def _api_supa_headers(token: str) -> dict:
    return {"apikey": str(st.secrets.get("SUPABASE_ANON_KEY") or ""),
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}


def _chiavi_api(token: str) -> list[dict]:
    r = _rq.get(
        _api_supa_url() + "/rest/v1/api_keys"
        "?select=id,name,prefix,created_at,last_used_at,revoked_at"
        "&order=created_at.desc&limit=50",
        headers=_api_supa_headers(token), timeout=15)
    if r.status_code != 200:
        st.error(f"Impossibile leggere le chiavi API ({r.status_code}): "
                 "hai eseguito lo script SQL della fase 3 su Supabase?")
        return []
    return r.json()


def _fmt_key_data(s) -> str:
    try:
        return auth.fmt_data(s)
    except Exception:
        return str(s or "—")


chiavi = _chiavi_api(sess["access_token"])
attive = [k for k in chiavi if not k.get("revoked_at")]

with st.expander("➕ Genera una nuova chiave", expanded=not attive):
    with st.form("nuova_chiave_form"):
        nome = st.text_input("Nome dello strumento (es. 'Power BI', 'Script report')",
                             max_chars=40, key="api_key_nome")
        genera = st.form_submit_button("Genera chiave", type="primary")
    if genera:
        if not nome.strip():
            st.error("Dai un nome alla chiave.")
        else:
            chiave_nuova = "ecm_" + _secrets.token_urlsafe(32)
            payload = {"name": nome.strip(),
                       "prefix": chiave_nuova[:11],
                       "key_hash": hashlib.sha256(chiave_nuova.encode()).hexdigest()}
            r = _rq.post(_api_supa_url() + "/rest/v1/api_keys",
                         headers={**_api_supa_headers(sess["access_token"]),
                                  "Prefer": "return=minimal"},
                         json=payload, timeout=15)
            if r.status_code not in (200, 201):
                st.error(f"Creazione fallita ({r.status_code}): {r.text[:200]}")
            else:
                st.success("✅ Chiave creata. Copiala ORA: non sarà più visibile.")
                st.code(chiave_nuova, language=None)
                st.caption("La tabella sotto si aggiorna al prossimo caricamento della pagina.")

if not chiavi:
    st.info("Nessuna chiave API creata finora.")
else:
    st.markdown("**Chiavi esistenti**")
    for k in chiavi:
        c1, c2 = st.columns([4, 1])
        stato = "🟢 Attiva" if not k.get("revoked_at") else "🔴 Revocata"
        with c1:
            st.markdown(
                f"**{k.get('name')}** · `{k.get('prefix')}…` · {stato} · "
                f"creata il {_fmt_key_data(k.get('created_at'))} · "
                f"ultimo uso: {_fmt_key_data(k.get('last_used_at'))}"
            )
        with c2:
            if not k.get("revoked_at") and st.button("Revoca", key=f"rev_{k['id']}",
                                                    use_container_width=True):
                r = _rq.patch(
                    _api_supa_url() + f"/rest/v1/api_keys?id=eq.{k['id']}",
                    headers=_api_supa_headers(sess["access_token"]),
                    json={"revoked_at": datetime.now(timezone.utc).isoformat()},
                    timeout=15)
                if r.status_code == 200:
                    st.success(f"Chiave '{k.get('name')}' revocata: entro 5 minuti ogni "
                               "richiesta con quella chiave verrà rifiutata.")
                    st.rerun()
                else:
                    st.error(f"Revoca fallita ({r.status_code}): {r.text[:200]}")
