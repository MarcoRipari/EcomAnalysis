import React, { useState } from "react";
import { useAuth } from "../lib/auth";
import { UnauthorizedError } from "../lib/api";
import { useTheme } from "../components/ui";

/* Schermata di login: unica credenziale = chiave API (ecm_...).
   Verifica contro /api/v1/me; la sessione resta in localStorage finche'
   non si fa logout o la chiave viene revocata. */

export default function Login() {
  const { t } = useTheme();
  const { login } = useAuth();
  const [key, setKey] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const inputStyle = {
    background: t.card, color: t.text, border: "1px solid " + t.border,
    borderRadius: 8, padding: "10px 12px", fontSize: 13, width: "100%",
    outline: "none",
  } as React.CSSProperties;

  const submit = async () => {
    const k = key.trim();
    if (!k) return;
    setBusy(true);
    setErr(null);
    try {
      await login(k);
      /* il re-render della shell sostituira' questa pagina */
    } catch (e) {
      if (e instanceof UnauthorizedError) setErr("Chiave non valida o revocata.");
      else setErr("Servizio non raggiungibile. Riprova piu' tardi.");
    } finally {
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

          <p className="text-sm font-bold mb-1">Accedi</p>
          <p className="text-xs mb-5" style={{ color: t.muted }}>
            Inserisci la tua chiave API per accedere alle analisi.
          </p>

          <label className="block">
            <span className="block text-[11px] font-semibold mb-1.5" style={{ color: t.muted }}>Chiave API</span>
            <input type="password" placeholder="ecm_..." value={key} style={inputStyle} autoFocus
                   onChange={(e) => setKey(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
          </label>

          {err && (
            <p className="text-xs font-semibold mt-3" style={{ color: t.negative }}>{err}</p>
          )}

          <button onClick={submit} disabled={busy || !key.trim()}
                  className="w-full mt-5 py-2.5 rounded-lg text-sm font-bold"
                  style={{ background: t.accent, color: "#FFFFFF", opacity: busy || !key.trim() ? 0.55 : 1 }}>
            {busy ? "Verifica..." : "Accedi"}
          </button>
        </div>
        <p className="text-center text-[11px] mt-4" style={{ color: t.muted }}>
          La chiave e le analisi restano sul tuo VPS.
        </p>
      </div>
    </div>
  );
}