import React, { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { getVenditeGroup, VenditeResp, UnauthorizedError } from "../lib/api";
import { Panel, Section, KpiCard, DataTable, fmtEUR, fmtInt, SERIES, useTheme } from "../components/ui";

/* Ordini del periodo aggregati per dimensione (vendite level=group):
   marketplace, nazione, brand, genere, taglia o acquirente. Ordini, righe,
   paia e fatturato per gruppo, con grafico e tabella guidati dai nomi
   colonna della risposta. */

const GRUPPI = [
  { v: "mkp", label: "Marketplace" },
  { v: "nazione", label: "Nazione" },
  { v: "brand", label: "Brand" },
  { v: "genere", label: "Genere" },
  { v: "taglia", label: "Taglia" },
  { v: "acquirente", label: "Acquirente" },
];

export default function Ordini({ da, a }: { da: string; a: string }) {
  const { t } = useTheme();
  const [group, setGroup] = useState("mkp");
  const [resp, setResp] = useState<VenditeResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [authErr, setAuthErr] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setAuthErr(false);
    setError(null);
    getVenditeGroup(da, a, group)
      .then((r) => { if (alive) { setResp(r); setLoading(false); } })
      .catch((e) => {
        if (!alive) return;
        if (e instanceof UnauthorizedError) setAuthErr(true);
        else setError(String(e.message ?? e));
        setLoading(false);
      });
    return () => { alive = false; };
  }, [da, a, group]);

  if (loading) {
    return <div className="py-16 text-center text-sm" style={{ color: t.muted }}>Caricamento...</div>;
  }
  if (authErr) {
    return (
      <div className="my-8 p-5 rounded-xl text-sm" style={{ border: "1px solid " + t.negative, color: t.text, background: t.card, boxShadow: t.shadow }}>
        <p className="font-bold" style={{ color: t.negative }}>API key mancante o non valida</p>
        <p className="mt-1.5 text-xs" style={{ color: t.muted }}>Imposta la chiave (ecm_...) nella sezione "API Key" della sidebar.</p>
      </div>
    );
  }
  if (error) {
    return <div className="my-8 p-5 rounded-xl text-sm" style={{ border: "1px solid " + t.negative, color: t.negative }}>{error}</div>;
  }

  const rows = resp?.dati ?? [];
  const colonne = rows.length ? Object.keys(rows[0]) : [];
  const findCol = (kw: string) => colonne.find((c) => c.toLowerCase().indexOf(kw) >= 0);
  const tot = (col?: string) => (col ? rows.reduce((s, r) => s + (Number(r[col]) || 0), 0) : 0);
  const ordiniCol = findCol("ordini");
  const fattCol = findCol("fatturato");
  const paiaCol = findCol("paia nette");
  const righeCol = findCol("righe");
  const nameCol = colonne[0];
  const gLabel = (GRUPPI.find((g) => g.v === group)?.label) ?? group;
  const chartRows = nameCol && ordiniCol
    ? rows.map((r) => ({ name: String(r[nameCol] ?? ""), v: Number(r[ordiniCol]) || 0 }))
        .sort((x, y) => y.v - x.v).slice(0, 8)
    : [];

  return (
    <div>
      {/* selettore dimensione di aggregazione */}
      <div className="flex flex-wrap gap-2 mb-6">
        {GRUPPI.map((g) => (
          <button key={g.v} onClick={() => setGroup(g.v)}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                  style={{ border: "1px solid " + (group === g.v ? t.accent : t.border),
                           color: group === g.v ? t.accent : t.muted, background: t.card }}>
            {g.label}
          </button>
        ))}
      </div>

      <div className="flex gap-3.5 flex-wrap">
        <KpiCard label="Ordini" value={fmtInt(tot(ordiniCol))} />
        <KpiCard label="Fatturato netto" value={fmtEUR(tot(fattCol))} />
        <KpiCard label="Paia nette" value={fmtInt(tot(paiaCol))} />
        <KpiCard label="Righe" value={fmtInt(tot(righeCol))} />
      </div>

      {chartRows.length > 0 && (
        <Section title={"Ordini per " + gLabel.toLowerCase()}>
          <Panel className="p-4">
            <div style={{ width: "100%", height: 260 }}>
              <ResponsiveContainer>
                <BarChart data={chartRows} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                  <CartesianGrid stroke={t.grid} vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: t.muted }} />
                  <YAxis tick={{ fontSize: 11, fill: t.muted }} width={60} />
                  <Tooltip formatter={(v) => fmtInt(Number(v))}
                           contentStyle={{ background: t.card, border: "1px solid " + t.border, borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="v" fill={SERIES[0]} radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </Section>
      )}

      <Section title={"Dettaglio per " + gLabel.toLowerCase()}>
        {rows.length ? <DataTable columns={colonne} rows={rows} /> : (
          <div className="text-center py-10 text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
            Nessuna riga nel periodo selezionato.
          </div>
        )}
      </Section>
    </div>
  );
}