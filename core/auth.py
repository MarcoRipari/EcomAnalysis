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
- Regola di sicurezza: l'accesso è concesso SOLO al livello aal2. Un account con
  fattori TOTP verificati chiede il codice a 6 cifre; un account senza fattori NON
  entra: al primo accesso l'app lo obbliga ad attivare la 2FA (QR + secret) prima
  di mostrare qualsiasi pagina.
- Regola tecnica: il cookie viene scritto/ripulito lato client con un micro-iframe
  JS. NON chiamare st.rerun() nello stesso run di una scrittura cookie: l'iframe
  non farebbe in tempo ad arrivare al browser. UNICA ECCEZIONE: dopo logout() è
  ammesso lo st.rerun(), perché il refresh token è già revocato lato Supabase (il
  run successivo, con refresh fallito, ripulisce comunque il cookie).

Secrets richiesti (Streamlit Cloud → Manage app → Secrets; in locale
.streamlit/secrets.toml, da NON committare):

    SUPABASE_URL      = "https://<progetto>.supabase.co"
    SUPABASE_ANON_KEY = "eyJ..."   # chiave "anon public", NON la service_role
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone

import requests
import streamlit as st
from streamlit.components.v1 import html as _iframe_html

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Rome")
except Exception:   # fuso non disponibile (raro): si resta sul fuso del server
    _TZ = timezone.utc

# ------------------------------------------------------------------ configurazione
DURATA_SESSIONE_GIORNI = 30   # durata "X": persistenza del login (cookie + refresh)
COOKIE_NAME = "ecom_sb_session"

# Nei run NON autenticati la sidebar viene nascosta via CSS (Streamlit non ha un'API
# per comprimerla programmaticamente): la schermata di login appare identica al primo
# accesso e dopo il logout, senza la strip vuota di sidebar. Il CSS sta DENTRO il
# placeholder della UI di accesso: appena l'autenticazione riesce il placeholder
# viene svuotato, il CSS sparisce e il menù torna visibile nello stesso run.
_CSS_NASCONDI_SIDEBAR = """
<style>
  section[data-testid="stSidebar"] { display: none !important; }
  div[data-testid="stSidebarCollapsedControl"] { display: none !important; }
  div[data-testid="collapsedControl"] { display: none !important; }
</style>
"""


class AuthError(Exception):
    """Errore di autenticazione con messaggio già pronto per l'utente."""


def fmt_data(iso: str) -> str:
    """Data ISO di Supabase (UTC) → '31/12/2026 24:59:59' nel fuso Europe/Rome."""
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return (iso or "").strip() or "—"


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
    # 204 No Content (es. POST /logout) o corpo non-JSON: nessun dato da restituire
    if not (r.text or "").strip():
        return {}
    try:
        return r.json()
    except ValueError:
        return {}


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
    sess["ha_fattori"] = any(f.get("status") == "verified" and f.get("factor_type") == "totp"
                             for f in list_factors(sess["access_token"]))
    return sess


# ------------------------------------------------------------------ API Supabase Auth
# Endpoint MFA di GoTrue (verificati sui sorgenti supabase/auth → internal/api/api.go):
#   POST   /auth/v1/factors                 → enroll (QR code + secret)
#   POST   /auth/v1/factors/{id}/challenge  → apre la challenge
#   POST   /auth/v1/factors/{id}/verify     → verifica il codice (nuova sessione aal2)
#   DELETE /auth/v1/factors/{id}            → rimuove il fattore
#   GET /auth/v1/factors NON ESISTE (sul router c'è solo POST /factors) → risponde
#   405 Method Not Allowed. L'elenco dei fattori si legge da GET /auth/v1/user,
#   campo "factors" dell'utente — è così che è implementato oggi supabase.auth.mfa.listFactors().
def list_factors(access_token: str) -> list[dict]:
    data = _call("GET", "user", access_token=access_token)
    user = data.get("user") or data   # copre entrambe le forme di risposta
    return user.get("factors") or []


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
               if f.get("status") == "verified" and f.get("factor_type") == "totp"]
    if not fattori:
        raise AuthError("Nessun fattore TOTP verificato su questo account.")
    fid = fattori[0]["id"]
    ch_id = challenge_factor(session["access_token"], fid)
    return verify_challenge(session["access_token"], fid, ch_id, code)


def confirm_enroll(session: dict, factor_id: str, code: str) -> dict:
    """Conferma un enroll appena generato (fattore ancora non verificato)."""
    ch_id = challenge_factor(session["access_token"], factor_id)
    return verify_challenge(session["access_token"], factor_id, ch_id, code)


def enroll_totp(access_token: str, friendly_name: str = "Accesso 2FA",
               issuer: str = "EcomApp") -> dict:
    # issuer = nome che l'app TOTP mostra per il secret ("EcomApp:test@test.it").
    # Se non lo si passa, GoTrue usa l'host del Site URL del progetto (es. "localhost:3000").
    data = _call("POST", "factors",
                 json_body={"factor_type": "totp", "friendly_name": friendly_name,
                            "issuer": issuer},
                 access_token=access_token)
    totp = data.get("totp") or {}
    return {"id": data.get("id"), "secret": totp.get("secret", ""),
            "uri": totp.get("uri", ""), "qr_code": totp.get("qr_code", "")}


def unenroll_factor(access_token: str, factor_id: str) -> None:
    _call("DELETE", f"factors/{factor_id}", access_token=access_token)


def pulisci_fattori(access_token: str) -> None:
    """Rimuove TUTTI i fattori TOTP dell'utente (verificati e non). Da chiamare PRIMA
    di un nuovo enroll: GoTrue rifiuta due fattori con lo stesso friendly_name
    (422 mfa_factor_name_conflict) e conta anche i non verificati nel limite massimo."""
    for f in list_factors(access_token):
        if f.get("factor_type") == "totp":
            try:
                unenroll_factor(access_token, f["id"])
            except Exception:
                pass


def update_password(access_token: str, nuova_password: str) -> None:
    """Cambia la password dell'utente autenticato (PUT /auth/v1/user)."""
    _call("PUT", "user", json_body={"password": nuova_password},
          access_token=access_token)


def refresh_session(refresh_token: str) -> dict:
    data = _call("POST", "token", params={"grant_type": "refresh_token"},
                 json_body={"refresh_token": refresh_token})
    return _completa_sessione(_session_from(data))


def revoke_session(session: dict) -> None:
    try:
        _call("POST", "logout", access_token=session["access_token"])
    except Exception:   # il logout non deve MAI fallire: è solo pulizia lato Supabase
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
    """Il cancello dell'app: si entra SOLO con una sessione a livello aal2.

    - Nessuna sessione → form di login.
    - Account con 2FA attiva → chiede il codice TOTP.
    - Primo accesso senza 2FA → obbliga ad attivarla qui (QR + secret) prima di entrare.
    Se l'autenticazione riesce nello stesso run, la UI di accesso viene pulita con
    st.empty() (NON con st.rerun), così il cookie scritto dall'iframe arriva al browser.
    """
    sess = get_session()
    if sess is not None and sess.get("aal") == "aal2":
        return sess

    _render_auth(sess)
    sess = st.session_state.get("auth")
    if sess is None or sess.get("aal") != "aal2":
        st.stop()
    return sess


def logout(session: dict) -> None:
    """Revoca la sessione su Supabase (il refresh token nel cookie diventa subito
    inutilizzabile) e pulisce memoria e cookie. Dopo logout() è AMMESSO st.rerun()
    (app.py lo fa per tornare subito alla login): anche se l'iframe di pulizia del
    cookie andasse perso nel rerun, il run successivo fallisce il refresh e ripulisce
    comunque il cookie."""
    revoke_session(session)
    st.session_state.pop("auth", None)
    st.session_state.pop("auth_pending", None)
    st.session_state.pop("auth_enroll", None)
    st.session_state.pop("_enroll_attivo", None)
    _clear_cookie()


# ------------------------------------------------------------------ UI
def qr_component(qr_code: str) -> None:
    """Disegna il QR dell'enroll TOTP. Attenzione: GoTrue NON restituisce un
    data-URI ma SVG puro ('<svg ...>...</svg>') — messo dentro <img src="...">
    l'HTML si vedrebbe come testo. Iniettato come markup inline invece si
    disegna perfettamente. (Usato dal cancello e dalla pagina Account.)"""
    qr = (qr_code or "").strip()
    if not qr:
        return
    if qr.startswith("<svg"):
        _iframe_html(
            qr.replace("<svg ", '<svg style="width:100%;height:auto;" ', 1),
            height=240,
        )
    else:   # fallback: data-URI o URL di un'immagine
        _iframe_html(f'<img src="{qr}" width="220" alt="QR TOTP"/>', height=240)


def _login_flow() -> None:
    ph = st.empty()   # placeholder: a login riuscito la UI di accesso sparisce SUBITO
    with ph.container():
        st.markdown(_CSS_NASCONDI_SIDEBAR, unsafe_allow_html=True)
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
        ph.empty()   # le box login spariscono nello STESSO run (nessuno st.rerun: il cookie arriva)
        if sess["ha_fattori"]:
            st.session_state["auth_pending"] = sess
            st.info("🔐 Questo account ha la 2FA attiva: inserisci il codice a 6 cifre.")
            _totp_flow(sess)
        else:
            st.session_state["auth_enroll"] = sess
            st.info("🔐 **Primo accesso**: prima di entrare devi attivare la 2FA qui sotto (una volta sola).")
            _enroll_flow(sess)


def _totp_flow(sess: dict) -> None:
    """Secondo fattore per account con 2FA già attiva."""
    ph = st.empty()
    with ph.container():
        st.markdown(_CSS_NASCONDI_SIDEBAR, unsafe_allow_html=True)
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
        ph.empty()
        st.success("✅ Codice verificato — accesso completato.")


def _enroll_flow(sess: dict) -> None:
    """Primo accesso senza 2FA: l'app la fa attivare PRIMA di entrare."""
    ph = st.empty()
    enroll = st.session_state.get("_enroll_attivo")
    if enroll is None:
        try:
            pulisci_fattori(sess["access_token"])   # via eventuali enroll incompleti (nome già usato)
            enroll = enroll_totp(sess["access_token"], "Accesso 2FA")
        except AuthError as e:
            st.error(f"Impossibile generare il QR per la 2FA: {e}")
            return
        st.session_state["_enroll_attivo"] = enroll   # riusato finché non viene confermato

    with ph.container():
        st.markdown(_CSS_NASCONDI_SIDEBAR, unsafe_allow_html=True)
        st.markdown("#### 1️⃣ Configura la tua app TOTP")
        st.caption(
            "Scansiona il QR con Google Authenticator, 1Password, Aegis, … "
            "oppure copia il **secret** a mano, poi conferma con il codice a 6 cifre."
        )
        c1, c2 = st.columns([1, 2])
        with c1:
            qr_component(enroll["qr_code"])
        with c2:
            st.markdown("**Secret** (inserimento manuale):")
            st.code(enroll["secret"], language=None)
            if enroll.get("uri"):
                st.caption(f"URI otpauth: `{enroll['uri']}`")
        with st.form("enroll_gate_form"):
            code = st.text_input("2️⃣ Codice a 6 cifre generato dall'app",
                                 max_chars=6, key="enroll_gate_code")
            ok = st.form_submit_button("3️⃣ Conferma e attiva la 2FA",
                                       type="primary", use_container_width=True)

    if ok:
        try:
            full = confirm_enroll(sess, enroll["id"], code.strip().replace(" ", ""))
        except AuthError as e:
            st.error(str(e))
            return
        st.session_state.pop("_enroll_attivo", None)
        st.session_state.pop("auth_enroll", None)
        remember_session(full)
        ph.empty()
        st.success("✅ 2FA attivata — accesso completato. Dal prossimo login verrà "
                   "chiesto anche il codice TOTP.")


def _render_auth(sess: dict | None) -> None:
    """L'unica UI del cancello: login, oppure passo TOTP, oppure enroll obbligatorio."""
    if "auth_enroll" in st.session_state:
        _enroll_flow(st.session_state["auth_enroll"])
    elif "auth_pending" in st.session_state:
        _totp_flow(st.session_state["auth_pending"])
    elif sess is not None and sess.get("ha_fattori"):
        _totp_flow(sess)          # sessione aal1 recuperata dal cookie, con 2FA attiva
    elif sess is not None:
        _enroll_flow(sess)        # sessione senza 2FA (caso raro): attivazione forzata
    else:
        _login_flow()
