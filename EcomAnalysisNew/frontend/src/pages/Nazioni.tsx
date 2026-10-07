import React, { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { getReport, ReportResp, Tabella, UnauthorizedError } from "../lib/api";
import { Panel, Section, DataTable, fmtEUR, SERIES, useTheme } from "../components/ui";

/* Nazioni dal report tipo=nazioni: tabelle "KPI per nazione" (una per anno,
   Global compresa) e "Share brand" per nazione e anno. Grafico = top nazioni
   per fatturato netto, con nome colonna e colonna fatturato rilevate dai nomi. */

export default function Nazioni({ da, a, confronti }: { da: string; a: string; confronti: number }) {
  const { t } = useTheme();
  const [resp, setResp] = useState<ReportResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [authErr, setAuthErr] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setAuthErr(false);
    setError(null);
    getReport("nazioni", da, a, confronti)
      .then((r) => { if (alive) { setResp(r); setLoading(false); } })
      .catch((e) => {
        if (!alive) return;
        if (e instanceof UnauthorizedError) setAuthErr(true);
        else setError(String(e.message ?? e));
        setLoading(false);
      });
    return () => { alive = false; };
  }, [da, a, confronti]);

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

  const tabelle = resp?.tabelle ?? [];
  const kpiTabs = tabelle.filter((x) => x.titolo.indexOf("KPI per nazione") >= 0);
  const shareTabs = tabelle.filter((x) => x.titolo.indexOf("Share brand") >= 0);
  const cur = kpiTabs[0];
  const nameCol = cur?.colonne[0];
  const fattCol = cur?.colonne.find((c) => c.toLowerCase().indexOf("fatturato") >= 0);
  const chartRows = cur && nameCol && fattCol
    ? cur.dati
        .map((r) => ({ name: String(r[nameCol] ?? ""), v: Number(r[fattCol]) || 0 }))
        .filter((x) => x.name.toUpperCase() !== "GLOBAL")
        .sort((x, y) => y.v - x.v)
        .slice(0, 8)
    : [];

  const DASH = String.fromCharCode(8212); /* separatore dei titoli dell'API */
  type ShareAnno = { y: string; tb: Tabella };
  const gruppi: Array<{ nazione: string; anni: ShareAnno[] }> = [];
  for (const tb of shareTabs) {
    const parti = tb.titolo.split(DASH).map((s) => s.trim());
    const nazione = parti.length >= 3 ? parti[1] : tb.titolo;
    const y = parti.length >= 3 ? parti[2] : "";
    let g = gruppi.find((x) => x.nazione === nazione);
    if (!g) { g = { nazione, anni: [] }; gruppi.push(g); }
    g.anni.push({ y, tb });
  }

  if (!tabelle.length) {
    return (
      <div className="text-center py-16 text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
        Nessun dato nel periodo selezionato.
      </div>
    );
  }

  return (
    <div>
      {kpiTabs.map((tb, i) => (
        <Section key={tb.titolo} title={tb.titolo}>
          {i === 0 && chartRows.length > 0 && (
            <Panel className="p-4 mb-4">
              <p className="text-xs font-semibold mb-3" style={{ color: t.muted }}>Top nazioni per fatturato netto (Global esclusa)</p>
              <div style={{ width: "100%", height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={chartRows} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                    <CartesianGrid stroke={t.grid} vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: t.muted }} />
                    <YAxis tick={{ fontSize: 11, fill: t.muted }} width={110}
                           tickFormatter={(v) => fmtEUR(Number(v))} />
                    <Tooltip formatter={(v) => fmtEUR(Number(v))}
                             contentStyle={{ background: t.card, border: "1px solid " + t.border, borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="v" fill={SERIES[0]} radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
          )}
          <DataTable columns={tb.colonne} rows={tb.dati} />
        </Section>
      ))}
      {gruppi.map((g) => (
        <Section key={g.nazione} title={"Share brand " + DASH + " " + g.nazione}>
          {g.anni.map((x) => (
            <div key={g.nazione + x.y} className="mb-4 last:mb-0">
              <p className="text-xs font-semibold mb-2" style={{ color: t.muted }}>{x.y}</p>
              <DataTable columns={x.tb.colonne} rows={x.tb.dati} />
            </div>
          ))}
        </Section>
      ))}
    </div>
  );
}