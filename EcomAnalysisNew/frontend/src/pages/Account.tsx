import React, { useEffect, useState } from "react";
import { getPeriodi, PeriodiResp } from "../lib/api";
import { useAuth } from "../lib/auth";
import * as sb from "../lib/supabase";
import { Panel, Section, KpiCard, DataTable, fmtInt, useTheme } from "../components/ui";

/* Account: sessione corrente (email Supabase o chiave API), attivazione 2FA
   TOTP, copertura dati e ultimi caricamenti. */

export default function Account() {
  const { t } = useTheme();
  const { me, email, mode, key, logout } = useAuth();
  const [per, setPer] = useState<PeriodiResp | null>(null);
  const [factors, setFactors] = useState<number | null>(null);
  const [enroll, setEnroll] = useState<{ id: string; secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getPeriodi().then((p) => { if (alive) setPer(p); }).catch(() => {});
    if (mode === "sb") {
      sb.listVerifiedTotp()
        .then((f) => { if (alive) setFactors(f.length); })
        .catch(() => { if (alive) setFactors(null); });
    }
    return () => { alive = false; };
  }, [mode]);

  const startEnroll = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const e = await sb.enrollTotp();
      setEnroll(e);
    } catch {
      setErr("Impossibile creare il fattore 2FA.");
    } finally {
      setBusy(false);
    }
  };

  const confirmCode = async () => {
    if (!enroll || code.trim().length < 6) return;
    setBusy(true); setErr(null);
    try {
      await sb.confirmEnroll(enroll.id, code.trim());
      setFactors(1);
      setEnroll(null);
      setCode("");
      setMsg("2FA attivata: d'ora in poi il login chiedera' il codice.");
    } catch {
      setErr("Codice non valido. Riprova.");
    } finally {
      setBusy(false);
    }
  };

  const righe = per?.righe ?? {};
  const car = per?.ultimiCaricamenti ?? [];
  const carCols = car.length ? Object.keys(car[0]) : [];
  const masked = key.length > 10 ? key.slice(0, 8) + "..." : key;

  const inputStyle = {
    background: t.card, color: t.text, border: "1px solid " + t.border,
    borderRadius: 8, padding: "10px 12px", fontSize: 13, width: "100%",
    outline: "none",
  } as React.CSSProperties;

  const btnStyle = {
    border: "1px solid " + t.border, color: t.negative, background: t.card,
  } as React.CSSProperties;

  return (
    <div className="max-w-4xl">
      <Panel className="p-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.06em]" style={{ color: t.muted }}>
          {mode === "sb" ? "Account utente" : "Chiave API"}
        </p>
        <p className="text-lg font-extrabold mt-1" style={{ color: t.text }}>
          {mode === "sb" ? (email ?? me?.nome ?? "Utente") : (me?.nome ?? "Chiave API")}
        </p>
        <p className="text-xs mt-1" style={{ color: t.muted }}>
          {mode === "sb" ? "Autenticazione attiva via " + (me?.via ?? "token utente Supabase")
                          : "Autenticazione attiva via " + (me?.via ?? "X-API-Key")}
        </p>
        {mode === "key" && (
          <p className="text-xs mt-2 font-mono" style={{ color: t.muted }}>{masked || "(nessuna chiave salvata)"}</p>
        )}
        <div className="flex gap-2 mt-4">
          <button onClick={logout} className="px-3 py-1.5 rounded-lg text-xs font-semibold" style={btnStyle}>
            Esci e torna al login
          </button>
        </div>
      </Panel>

      {mode === "sb" && (
        <Section title="Autenticazione a due fattori (TOTP)">
          {factors === null ? (
            <p className="text-xs" style={{ color: t.muted }}>Stato 2FA non disponibile.</p>
          ) : factors > 0 ? (
            <p className="text-sm font-semibold" style={{ color: t.positive }}>2FA attiva su questo account.</p>
          ) : enroll ? (
            <Panel className="p-4">
              <p className="text-xs mb-2" style={{ color: t.muted }}>
                Aggiungi questa chiave alla tua app authenticator (inserimento manuale), poi conferma con il codice generato.
              </p>
              <p className="text-xs font-mono break-all mb-3" style={{ color: t.text }}>Segreto: {enroll.secret}</p>
              <p className="text-[10px] font-mono break-all mb-4" style={{ color: t.muted }}>{enroll.uri}</p>
              <input type="text" inputMode="numeric" placeholder="000000" value={code} style={inputStyle}
                     onChange={(e) => setCode(e.target.value)}
                     onKeyDown={(e) => { if (e.key === "Enter") confirmCode(); }} />
              {err && <p className="text-xs font-semibold mt-2" style={{ color: t.negative }}>{err}</p>}
              <button onClick={confirmCode} disabled={busy || code.trim().length < 6}
                      className="mt-3 px-3.5 py-2 rounded-lg text-xs font-bold"
                      style={{ background: t.accent, color: "#FFFFFF",
                               opacity: busy || code.trim().length < 6 ? 0.55 : 1 }}>
                {busy ? "Verifica..." : "Conferma e attiva"}
              </button>
            </Panel>
          ) : (
            <div>
              <p className="text-xs mb-3" style={{ color: t.muted }}>
                Nessun fattore 2FA attivo. Consigliato: protegge l'account anche se la password viene scoperta.
              </p>
              {msg && <p className="text-xs font-semibold mb-2" style={{ color: t.positive }}>{msg}</p>}
              {err && <p className="text-xs font-semibold mb-2" style={{ color: t.negative }}>{err}</p>}
              <button onClick={startEnroll} disabled={busy}
                      className="px-3.5 py-2 rounded-lg text-xs font-bold"
                      style={{ background: t.accent, color: "#FFFFFF", opacity: busy ? 0.55 : 1 }}>
                {busy ? "Creazione..." : "Attiva 2FA"}
              </button>
            </div>
          )}
        </Section>
      )}

      {per && (
        <div>
          <div className="flex gap-3.5 flex-wrap mt-6">
            <KpiCard label="Righe totali" value={fmtInt(Number(righe.righe_totali ?? 0))} />
            <KpiCard label="Spediti" value={fmtInt(Number(righe.spediti ?? 0))} />
            <KpiCard label="Resi" value={fmtInt(Number(righe.resi ?? 0))} />
            <KpiCard label="Rimborsi standalone" value={fmtInt(Number(righe.standalone ?? 0))} />
          </div>
          <p className="text-xs mt-3" style={{ color: t.muted }}>
            Dati in DB dal {per.copertura.da} al {per.copertura.a}.
          </p>

          <Section title="Ultimi caricamenti">
            {car.length ? <DataTable columns={carCols} rows={car} /> : (
              <div className="text-center py-10 text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
                Nessun caricamento registrato.
              </div>
            )}
          </Section>
        </div>
      )}
    </div>
  );
}
