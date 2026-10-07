import React from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useReport } from "../lib/store";
import { ReportResp, Tabella } from "../lib/store-types";
import { Panel, Section, DataTable, Loading, LoadErr, fmtEUR, SERIES, useTheme } from "../components/ui";

/* Nazioni dal report tipo=nazioni (dati dalla cache unica): KPI per nazione
   (una tabella per anno, Global compresa), grafico top nazioni per fatturato
   e share brand raggruppati per nazione e anno. */

export default function Nazioni({ da, a, confronti }: { da: string; a: string; confronti: number }) {
  const { t } = useTheme();
  const r = useReport("nazioni", da, a, confronti);
  if (r.loading) return <Loading />;
  if (r.authErr) return <LoadErr auth />;
  if (r.error) return <LoadErr auth={false} error={r.error} />;

  const resp: ReportResp | null = r.data ?? null;
  const tabelle = resp?.tabelle ?? [];
  const kpiTabs = tabelle.filter((x) => x.titolo.indexOf("KPI per nazione") >= 0);
  const shareTabs = tabelle.filter((x) => x.titolo.indexOf("Share brand") >= 0);
  const cur = kpiTabs[0];
  const nameCol = cur?.colonne[0];
  const fattCol = cur?.colonne.find((c) => c.toLowerCase().indexOf("fatturato") >= 0);
  const chartRows = cur && nameCol && fattCol
    ? cur.dati
        .map((row) => ({ name: String(row[nameCol] ?? ""), v: Number(row[fattCol]) || 0 }))
        .filter((x) => x.name.toUpperCase() !== "GLOBAL")
        .sort((x, y) => y.v - x.v)
        .slice(0, 8)
    : [];

  const DASH = String.fromCharCode(8212);
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
