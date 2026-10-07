import React, { useEffect, useState } from "react";
import { getPeriodi, PeriodiResp } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Panel, Section, KpiCard, DataTable, fmtInt, useTheme } from "../components/ui";

/* Account: chiave API in uso (verificata al login, dati da AuthProvider),
   copertura dei dati nel DB, conteggi righe e ultimi caricamenti. */

export default function Account() {
  const { t } = useTheme();
  const { me, key, logout } = useAuth();
  const [per, setPer] = useState<PeriodiResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getPeriodi()
      .then((p) => { if (alive) setPer(p); })
      .catch(() => { if (alive) setError("Copertura dati non disponibile."); });
    return () => { alive = false; };
  }, []);

  const masked = key.length > 10 ? key.slice(0, 8) + "..." : key;
  const righe = per?.righe ?? {};
  const car = per?.ultimiCaricamenti ?? [];
  const carCols = car.length ? Object.keys(car[0]) : [];

  return (
    <div className="max-w-4xl">
      <Panel className="p-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.06em]" style={{ color: t.muted }}>Chiave API</p>
        <p className="text-lg font-extrabold mt-1" style={{ color: me ? t.positive : t.muted }}>
          {me?.nome ?? "Utente"}
        </p>
        <p className="text-xs mt-1" style={{ color: t.muted }}>
          Autenticazione attiva via {me?.via ?? "X-API-Key"}
        </p>
        <p className="text-xs mt-2 font-mono" style={{ color: t.muted }}>{masked || "(nessuna chiave salvata)"}</p>
        <div className="flex gap-2 mt-4">
          <button onClick={logout}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                  style={{ border: "1px solid " + t.border, color: t.negative, background: t.card }}>
            Esci e torna al login
          </button>
        </div>
      </Panel>

      {error && <p className="text-xs mt-4" style={{ color: t.negative }}>{error}</p>}

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