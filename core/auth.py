"""
Autenticazione Supabase (email + password) con secondo fattore TOTP (2FA) e sessione
persistente fra refresh della pagina e riapertura del browser.

Come funziona
-------------
- Login e verifica TOTP via REST API di Supabase Auth ("/auth/v1/...") con requests:
  nessuna dipendenza SDK, nessun peso extra per Streamlit Cloud.
- La sessione autenticata (access token + refresh token) vive in st.session_state
  durante la sessione Streamlit. st.session_state NON sopravvive al refresh della
  pagina (F5 = nuova sessione Streamlit), quindi il REFRESH token viene anche
  scritto in un cookie di durata DURATA_SESSIONE_GIORNI: al primo avvio di ogni
  sessione lo si legge, si rinfresca il token e si rientra senza rifare il login.
- Supabase ruota i refresh token a ogni uso: ogni refresh riscrive il cookie col
  token nuovo (l'app lo fa da sola).
- Regola di sicurezza: quando un account ha fattori TOTP verificati, l'accesso è
  concesso solo al livello aal2 (dopo il codice TOTP). Gli account senza fattori
  entrano con aal1 e possono attivare la 2FA dalla pagina 🔐 Account.
- Regola tecnica: il cookie viene scritto/ripulito lato client con un micro-iframe
  JS. NON chiamare st.rerun() nello stesso run di una scrittura cookie: l'iframe
  non farebbe in tempo ad arrivare al browser.

Secrets richiesti (Streamlit Cloud → Manage app → Secrets; in locale
.streamlit/secrets.toml, da NON committare):

    SUPABASE_URL      = "https://<progetto>.supabase.co"
    SUPABASE_ANON_KEY = "eyJ..."   # chiave "anon public", NON la service_role
"""
from __future__ import annotations

import base64
import json
import time

import requests
import streamlit as st
from streamlit.components.v1 import html as _iframe_html

# ------------------------------------------------------------------ configurazione
DURATA_SESSIONE_GIORNI = 30   # durata "X": persistenza del login (cookie + refresh)
COOKIE_NAME = "ecom_sb_session"


class AuthError(Exception):
    """Errore di autenticazione con messaggio già pronto per l'utente."""


# ------------------------------------------------------------------ client REST
def _ensure_config() -> None:
    if st.session_state.get("_sb_config_ok"):
        return
    url = str(st.secrets.get("SUPABASE_URL") or "").strip().strip('"\'')
    key = str(st.secrets.get("SUPABASE_ANON_KEY") or "").strip().strip('"\'')
    if not url or not key:
        st.error(
            "Secrets mancanti: configura **SUPABASE_URL** e **SUPABASE_ANON_KEY** "
            "(chiave Publishable/anon di Supabase) nei secrets di Streamlit."
        )
        st.stop()
    # Igiene dell'URL: via spazi e virgolette, via slash finale e, soprattutto, via
    # un eventuale "/auth/v1" o "/auth" già presente (verrebbe duplicato in _call → 404)
    url = url.rstrip("/")
    for suffisso in ("/auth/v1", "/auth"):
        if url.endswith(suffisso):
            url = url[: -len(suffisso)].rstrip("/")
    if not url.startswith("https://") or "." not in url:
        st.error(
            f"**SUPABASE_URL non valida**: deve essere nella forma "
            f"https://&lt;progetto&gt;.supabase.co (valore letto: “{url}”)."
        )
        st.stop()
    st.session_state["_sb_url"] = url
    st.session_state["_sb_anon_key"] = key
    st.session_state["_sb_config_ok"] = True


def _headers(access_token: str | None = None) -> dict:
    _ensure_config()
    h = {"apikey": st.session_state["_sb_anon_key"], "Content-Type": "application/json"}
    if access_token:
        h["Authorization"] = f"Bearer {access_token}"
    return h


def _traduci(msg: str) -> str:
    m = msg.lower()
    if "invalid login credentials" in m:
        return "Email o password non validi."
    if "email not confirmed" in m:
        return ("Email non ancora confermata: controlla la posta (o conferma l'utente "
                "dalla dashboard Supabase).")
    if "otp" in m or "challenge" in m or "totp" in m or "two-factor" in m:
        return "Codice TOTP non valido o scaduto: riprova con il codice attuale dell'app."
    if "refresh" in m:
        return "Sessione scaduta o revocata: rifai l'accesso."
    if "rate limit" in m or "too many" in m:
        return "Troppi tentativi: attendi qualche minuto e riprova."
    return f"Errore di autenticazione: {msg}"


def _call(method: str, path: str, *, json_body=None, params=None, access_token=None) -> dict:
    url = f"{st.session_state['_sb_url']}/auth/v1/{path}"
    try:
        r = requests.request(method, url, json=json_body, params=params,
                              headers=_headers(access_token), timeout=20)
    except requests.RequestException as e:
        raise AuthError(f"Errore di rete verso Supabase: {e}")
    if r.status_code >= 400:
        try:
            err = r.json()
        except ValueError:
            corpo = (r.text or "")[:300].strip()
            if r.status_code == 404:
                raise AuthError(
                    f"**404 da Supabase** su `/{path}`: endpoint non trovato. Nel 99% dei "
                    f"casi SUPABASE_URL non è quella giusta — deve essere ESATTAMENTE "
                    f"https://<progetto>.supabase.co, senza percorsi extra. "
                    f"Valore in uso: {st.session_state['_sb_url']}. "
                    f"Verifica aprendo nel browser "
                    f"{st.session_state['_sb_url']}/auth/v1/health "
                    f"(deve mostrare un JSON GoTrue). Dettagli: {corpo or 'nessun corpo'}"
                )
            raise AuthError(
                f"Supabase ha risposto con errore {r.status_code}: {corpo or 'nessun dettaglio'}"
            )
        msg = (err.get("error_description") or err.get("msg") or err.get("message")
               or err.get("error") or "").strip()
        if not msg:
            msg = (r.text or "")[:200].strip() or f"HTTP {r.status_code}"
        raise AuthError(_traduci(msg))
    return r.json()


# ------------------------------------------------------------------ sessione/JWT
def _jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def _session_from(data: dict) -> dict:
    tok = data["access_token"]
    p = _jwt_payload(tok)
    return {
        "access_token": tok,
        "refresh_token": data["refresh_token"],
        "expires_at": int(p.get("exp", time.time() + 3600)),
        "user": data.get("user") or {},
        "aal": p.get("aal", "aal1"),
        "ha_fattori": False,   # ricalcolato da _completa_sessione
    }


def _completa_sessione(sess: dict) -> dict:
    """Aggiunge sess['ha_fattori'] = True se esiste almeno un fattore TOTP verificato."""
    sess["ha_fattori"] = any(f.get("status") == "verified"
                             for f in list_factors(sess["access_token"]))
    return sess


# ------------------------------------------------------------------ API Supabase Auth
# Endpoint MFA di GoTrue (verificati): /auth/v1/factors — NON /auth/v1/mfa/...
def list_factors(access_token: str) -> list[dict]:
    return _call("GET", "factors", access_token=access_token)


def sign_in_with_password(email: str, password: str) -> dict:
    data = _call("POST", "token", params={"grant_type": "password"},
                 json_body={"email": email, "password": password})
    return _completa_sessione(_session_from(data))


def challenge_factor(access_token: str, factor_id: str) -> str:
    ch = _call("POST", f"factors/{factor_id}/challenge",
               access_token=access_token)
    return ch["id"]


def verify_challenge(access_token: str, factor_id: str, challenge_id: str, code: str) -> dict:
    """Verifica il codice TOTP; ritorna la NUOVA sessione a livello aal2."""
    data = _call("POST", f"factors/{factor_id}/verify",
                 json_body={"challenge_id": challenge_id, "code": code},
                 access_token=access_token)
    return _completa_sessione(_session_from(data))


def verify_totp(session: dict, code: str) -> dict:
    """Step-up al login: cerca il fattore TOTP verificato e verifica il codice."""
    fattori = [f for f in list_factors(session["access_token"])
               if f.get("status") == "verified"]
    if not fattori:
        raise AuthError("Nessun fattore TOTP verificato su questo account.")
    fid = fattori[0]["id"]
    ch_id = challenge_factor(session["access_token"], fid)
    return verify_challenge(session["access_token"], fid, ch_id, code)


def confirm_enroll(session: dict, factor_id: str, code: str) -> dict:
    """Conferma un enroll appena generato (fattore ancora non verificato)."""
    ch_id = challenge_factor(session["access_token"], factor_id)
    return verify_challenge(session["access_token"], factor_id, ch_id, code)


def enroll_totp(access_token: str, friendly_name: str = "App TOTP") -> dict:
    data = _call("POST", "factors",
                 json_body={"factor_type": "totp", "friendly_name": friendly_name},
                 access_token=access_token)
    totp = data.get("totp") or {}
    return {"id": data.get("id"), "secret": totp.get("secret", ""),
            "uri": totp.get("uri", ""), "qr_code": totp.get("qr_code", "")}


def unenroll_factor(access_token: str, factor_id: str) -> None:
    _call("DELETE", f"factors/{factor_id}", access_token=access_token)


def refresh_session(refresh_token: str) -> dict:
    data = _call("POST", "token", params={"grant_type": "refresh_token"},
                 json_body={"refresh_token": refresh_token})
    return _completa_sessione(_session_from(data))


def revoke_session(session: dict) -> None:
    try:
        _call("POST", "logout", access_token=session["access_token"])
    except AuthError:
        pass


# ------------------------------------------------------------------ cookie (lato browser)
def _write_cookie(refresh_token: str) -> None:
    """Scrive/aggiorna il cookie. NON chiamare st.rerun() nello stesso run."""
    max_age = DURATA_SESSIONE_GIORNI * 86400
    _iframe_html(
        f"<script>document.cookie = '{COOKIE_NAME}={refresh_token}; "
        f"max-age={max_age}; path=/; SameSite=Lax';</script>",
        height=0,
    )


def _clear_cookie() -> None:
    _iframe_html(
        f"<script>document.cookie = '{COOKIE_NAME}=; max-age=0; path=/; SameSite=Lax';</script>",
        height=0,
    )


def remember_session(sess: dict) -> None:
    """Salva la sessione in memoria e aggiorna il cookie (NON rerunare dopo)."""
    st.session_state["auth"] = sess
    _write_cookie(sess["refresh_token"])


# ------------------------------------------------------------------ orchestrazione
def get_session() -> dict | None:
    """Sessione corrente se valida; altrimenti prova a recuperarla dal cookie."""
    _ensure_config()
    sess = st.session_state.get("auth")
    if sess and sess.get("expires_at", 0) > time.time() + 60:
        return sess

    # nessuna sessione in memoria (prima visita, F5, token scaduto): parti dal cookie
    rt = st.context.cookies.get(COOKIE_NAME)
    if not rt:
        st.session_state.pop("auth", None)
        return None
    try:
        nuova = refresh_session(rt)
    except AuthError:
        st.session_state.pop("auth", None)
        _clear_cookie()
        return None
    st.session_state["auth"] = nuova
    _write_cookie(nuova["refresh_token"])   # rotazione: cookie col token nuovo
    return nuova


def require_session() -> dict:
    """Il cancello dell'app: form di login (+ passo TOTP) se non autenticati.

    Se l'utente si autentica in questo stesso run, ritorna la sessione nuova SENZA
    rerun (il cookie deve prima arrivare al browser).
    """
    sess = get_session()

    if sess is None:
        _render_login()
        sess = st.session_state.get("auth")
        if sess is None:
            st.stop()

    if sess.get("aal") != "aal2" and sess.get("ha_fattori"):
        _render_totp(sess)
        sess = st.session_state.get("auth")
        if sess is None:
            st.stop()

    return sess


def logout(session: dict) -> None:
    """Revoca su Supabase, pulisce memoria e cookie. NON chiamare st.rerun() dopo:
    il run corrente termina (st.stop in app.py), il cookie pulito arriva al browser
    e il run successivo mostra la login."""
    revoke_session(session)
    st.session_state.pop("auth", None)
    st.session_state.pop("auth_pending", None)
    _clear_cookie()


# ------------------------------------------------------------------ UI
def _render_login() -> None:
    st.markdown("### 🔐 Accesso")
    st.caption("Inserisci le credenziali del tuo account (utenti gestiti in Supabase).")
    with st.form("login_form"):
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pwd")
        entra = st.form_submit_button("Accedi", type="primary", use_container_width=True)

    if entra:
        try:
            sess = sign_in_with_password(email.strip(), password)
        except AuthError as e:
            st.error(str(e))
            return
        if sess["aal"] == "aal2" or not sess["ha_fattori"]:
            remember_session(sess)
            st.success("Accesso riuscito ✅")
        else:
            # account con 2FA attiva: serve il codice TOTP (in questo stesso run)
            st.session_state["auth_pending"] = sess
            st.info("🔐 Questo account ha la 2FA attiva: inserisci il codice a 6 cifre.")

    if "auth_pending" in st.session_state:
        _render_totp(st.session_state["auth_pending"])


def _render_totp(sess: dict) -> None:
    with st.form("totp_form"):
        code = st.text_input("Codice TOTP (6 cifre)", max_chars=6, key="totp_code")
        ok = st.form_submit_button("Verifica", type="primary", use_container_width=True)
    if ok:
        try:
            full = verify_totp(sess, code.strip().replace(" ", ""))
        except AuthError as e:
            st.error(str(e))
            return
        st.session_state.pop("auth_pending", None)
        remember_session(full)
        st.success("✅ Codice verificato — accesso completato.")
