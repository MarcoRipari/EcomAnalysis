import React, { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import * as sb from "../lib/supabase";
import { useAuth } from "../lib/auth";
import { UnauthorizedError } from "../lib/api";
import { useTheme } from "../components/ui";

/* Login con due modalita': email + password (con 2FA TOTP se l'utente ha un
   fattore verificato) oppure chiave API ecm_... */

export default function Login() {
  const { t } = useTheme();
  const { loginWithKey, loginStartEmail, loginVerifyCode } = useAuth();
  const [tab, setTab] = useState<"email" | "key">("email");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [key, setKey] = useState("");
  const [code, setCode] = useState("");
  const [mfa, setMfa] = useState<{ factorId: string; challengeId: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inputStyle = {
    background: t.card, color: t.text, border: "1px solid " + t.border,
    borderRadius: 8, padding: "10px 12px", fontSize: 13, width: "100%",
    outline: "none",
  } as React.CSSProperties;

  const submitEmail = async () => {
    if (!email.trim() || !password) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await loginStartEmail(email.trim(), password);
      if (r.needsCode && r.factorId && r.challengeId) {
        setMfa({ factorId: r.factorId, challengeId: r.challengeId });
      }
    } catch (e) {
      const c = String((e as { code?: string })?.code ?? "");
      if (c === "invalid_credentials") setErr("Email o password non validi.");
      else if (c === "email_not_confirmed") setErr("Email non confermata.");
      else setErr(String((e as Error)?.message ?? "Errore di accesso."));
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async () => {
    if (!mfa || code.trim().length < 6) return;
    setBusy(true);
    setErr(null);
    try {
      await loginVerifyCode(mfa.factorId, mfa.challengeId, code.trim());
    } catch {
      setErr("Codice non valido. Riprova.");
    } finally {
      setBusy(false);
    }
  };

  const submitKey = async () => {
    const k = key.trim();
    if (!k) return;
    setBusy(true);
    setErr(null);
    try {
      await loginWithKey(k);
    } catch (e) {
      if (e instanceof UnauthorizedError) setErr("Chiave non valida o revocata.");
      else setErr("Servizio non raggiungibile. Riprova piu' tardi.");
    } finally {
      setBusy(false);
    }
  };

  const tabBtn = (v: "email" | "key", label: string) => (
    <button onClick={() => { setTab(v); setErr(null); setMfa(null); }}
            className={"px-3.5 py-2 rounded-lg text-xs font-semibold flex-1"}
            style={{ border: "1px solid " + (tab === v ? t.accent : t.border),
                     color: tab === v ? t.accent : t.muted, background: t.card }}>
      {label}
    </button>
  );

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: t.bg }}>
      <div className="w-full max-w-sm px-4">
        <div className="rounded-xl px-6 py-8"
             style={{ background: t.surface, border: "1px solid " + t.border, boxShadow: t.shadow }}>
          <div className="flex items-center gap-2.5 mb-6">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-black"
                 style={{ background: t.accentSoft, color: t.accent }}>EA</div>
            <div>
              <p className="text-base font-bold leading-tight">EcomAnalysis</p>
              <p className="text-[11px]" style={{ color: t.muted }}>Retail Analytics</p>
            </div>
          </div>

          {mfa ? (
            <div>
              <p className="text-sm font-bold mb-1">Verifica in due passaggi</p>
              <p className="text-xs mb-5" style={{ color: t.muted }}>
                Inserisci il codice a 6 cifre dalla tua app authenticator.
              </p>
              <input type="text" inputMode="numeric" placeholder="000000" value={code} style={inputStyle} autoFocus
                     onChange={(e) => setCode(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") submitCode(); }} />
              {err && <p className="text-xs font-semibold mt-3" style={{ color: t.negative }}>{err}</p>}
              <button onClick={submitCode} disabled={busy || code.trim().length < 6}
                      className="w-full mt-5 py-2.5 rounded-lg text-sm font-bold"
                      style={{ background: t.accent, color: "#FFFFFF", opacity: busy || code.trim().length < 6 ? 0.55 : 1 }}>
                {busy ? "Verifica..." : "Verifica codice"}
              </button>
            </div>
          ) : (
            <div>
              <div className="flex gap-2 mb-5">
                {tabBtn("email", "Email e password")}
                {tabBtn("key", "Chiave API")}
              </div>

              {tab === "email" ? (
                <div>
                  <label className="block mb-3">
                    <span className="block text-[11px] font-semibold mb-1.5" style={{ color: t.muted }}>Email</span>
                    <input type="email" placeholder="nome@esempio.it" value={email} style={inputStyle}
                           onChange={(e) => setEmail(e.target.value)}
                           onKeyDown={(e) => { if (e.key === "Enter") submitEmail(); }} />
                  </label>
                  <label className="block">
                    <span className="block text-[11px] font-semibold mb-1.5" style={{ color: t.muted }}>Password</span>
                    <input type="password" placeholder="Password" value={password} style={inputStyle}
                           onChange={(e) => setPassword(e.target.value)}
                           onKeyDown={(e) => { if (e.key === "Enter") submitEmail(); }} />
                  </label>
                  {err && <p className="text-xs font-semibold mt-3" style={{ color: t.negative }}>{err}</p>}
                  <button onClick={submitEmail} disabled={busy || !email.trim() || !password}
                          className="w-full mt-5 py-2.5 rounded-lg text-sm font-bold"
                          style={{ background: t.accent, color: "#FFFFFF", opacity: busy || !email.trim() || !password ? 0.55 : 1 }}>
                    {busy ? "Accesso..." : "Accedi"}
                  </button>
                </div>
              ) : (
                <div>
                  <label className="block">
                    <span className="block text-[11px] font-semibold mb-1.5" style={{ color: t.muted }}>Chiave API</span>
                    <input type="password" placeholder="ecm_..." value={key} style={inputStyle}
                           onChange={(e) => setKey(e.target.value)}
                           onKeyDown={(e) => { if (e.key === "Enter") submitKey(); }} />
                  </label>
                  {err && <p className="text-xs font-semibold mt-3" style={{ color: t.negative }}>{err}</p>}
                  <button onClick={submitKey} disabled={busy || !key.trim()}
                          className="w-full mt-5 py-2.5 rounded-lg text-sm font-bold"
                          style={{ background: t.accent, color: "#FFFFFF", opacity: busy || !key.trim() ? 0.55 : 1 }}>
                    {busy ? "Verifica..." : "Accedi"}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
        <p className="text-center text-[11px] mt-4" style={{ color: t.muted }}>
          La chiave, l'account e le analisi restano sul tuo VPS.
        </p>
      </div>
    </div>
  );
}

/* Gate 2FA obbligatorio: mostrata SOLO quando la sessione e' attiva ma non
   esiste un fattore TOTP verificato. Stessa card del login, senza tabs e
   senza via d'uscita: l'utente attiva il 2FA (QR + conferma codice) oppure
   esce. Nessun dato del sito viene caricato o mostrato finche' resta qui. */

export function ForcedMfa() {
  const { t } = useTheme();
  const { email, logout, clearMfaPending } = useAuth();
  const [enroll, setEnroll] = useState<{ id: string; secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState(false);

  const inputStyle = {
    background: t.card, color: t.text, border: "1px solid " + t.border,
    borderRadius: 8, padding: "10px 12px", fontSize: 13, width: "100%",
    outline: "none",
  } as React.CSSProperties;

  useEffect(() => {
    let alive = true;
    if (started) return;
    setStarted(true);
    setBusy(true);
    (async () => {
      try {
        const e = await sb.enrollTotp();
        if (alive) setEnroll(e);
      } catch (x) {
        if (alive) setErr("Impossibile creare il fattore 2FA: " +
          String((x as Error)?.message ?? (x as { code?: string })?.code ?? "errore sconosciuto"));
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => { alive = false; };
  }, [started]);

  const confirmCode = async () => {
    if (!enroll || code.trim().length < 6) return;
    setBusy(true);
    setErr(null);
    try {
      await sb.confirmEnroll(enroll.id, code.trim());
      clearMfaPending();
    } catch {
      setErr("Codice non valido. Riprova.");
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: t.bg }}>
      <div className="w-full max-w-sm px-4">
        <div className="rounded-xl px-6 py-8"
             style={{ background: t.surface, border: "1px solid " + t.border, boxShadow: t.shadow }}>
          <div className="flex items-center gap-2.5 mb-6">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-black"
                 style={{ background: t.accentSoft, color: t.accent }}>EA</div>
            <div>
              <p className="text-base font-bold leading-tight">EcomAnalysis</p>
              <p className="text-[11px]" style={{ color: t.muted }}>Retail Analytics</p>
            </div>
          </div>

          <p className="text-sm font-bold mb-1">Attivazione 2FA obbligatoria</p>
          <p className="text-xs mb-5" style={{ color: t.muted }}>
            L'accesso al sito e' bloccato finche' non attivi l'autenticazione a due fattori
            per l'account {email ?? "corrente"}.
          </p>

          {enroll ? (
            <div>
              <div className="p-3 rounded-lg mb-4 flex justify-center"
                   style={{ background: "#FFFFFF", border: "1px solid " + t.border }}>
                <QRCodeSVG value={enroll.uri} size={150} />
              </div>
              <p className="text-xs mb-2" style={{ color: t.muted }}>
                Scansiona il QR con la tua app authenticator (Google Authenticator, Authy, 1Password...)
                oppure inserisci il codice manuale, poi conferma con il codice a 6 cifre generato.
              </p>
              <p className="text-xs font-mono break-all mb-3" style={{ color: t.text }}>
                Codice manuale: {enroll.secret}
              </p>
              <input type="text" inputMode="numeric" placeholder="000000" value={code} style={inputStyle} autoFocus
                     onChange={(e) => setCode(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") confirmCode(); }} />
              {err && <p className="text-xs font-semibold mt-2" style={{ color: t.negative }}>{err}</p>}
              <button onClick={confirmCode} disabled={busy || code.trim().length < 6}
                      className="w-full mt-4 py-2.5 rounded-lg text-sm font-bold"
                      style={{ background: t.accent, color: "#FFFFFF", opacity: busy || code.trim().length < 6 ? 0.55 : 1 }}>
                {busy ? "Verifica..." : "Conferma e attiva"}
              </button>
            </div>
          ) : (
            <div>
              {err && <p className="text-xs font-semibold mb-3" style={{ color: t.negative }}>{err}</p>}
              <p className="text-xs mb-4" style={{ color: t.muted }}>
                {busy ? "Preparazione del fattore 2FA..." : "In attesa del fattore 2FA."}
              </p>
            </div>
          )}

          <button onClick={logout}
                  className="w-full mt-5 py-2 rounded-lg text-xs font-semibold"
                  style={{ border: "1px solid " + t.border, color: t.negative, background: t.card }}>
            Esci e torna al login
          </button>
        </div>
        <p className="text-center text-[11px] mt-4" style={{ color: t.muted }}>
          La chiave, l'account e le analisi restano sul tuo VPS.
        </p>
      </div>
    </div>
  );
}
