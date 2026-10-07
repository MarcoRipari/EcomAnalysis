import React, { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { getMensileReport, ReportResp, UnauthorizedError } from "../lib/api";
import { Section, KpiCard, DataTable, fmtEUR, fmtInt, fmtVar, fmtPct, SERIES, useTheme } from "../components/ui";

/* Pagina Y2Y: un solo endpoint (report tipo=mensile) con cui costruisce KPI,
   grafico mese-per-mese a finestra mobile e tabelle stagioni SS/FW. Tutto guidato
   dai nomi colonna dell API: nessun valore cablato. */

export default function Y2Y({ da, a, confronti }: { da: string; a: string; confronti: number }) {
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
    getMensileReport(da, a, confronti)
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
      <div className="my-8 p-5 rounded-xl text-sm" style={{ border: "1px solid " + t.negative, color: t.text, background: t.card }}>
        <p className="font-bold" style={{ color: t.negative }}>API key mancante o non valida</p>
        <p className="mt-1.5 text-xs" style={{ color: t.muted }}>Imposta la chiave (prefisso ecm_) nella sezione "API Key" della sidebar.</p>
      </div>
    );
  }
  if (error) {
    return <div className="my-8 p-5 rounded-xl text-sm" style={{ border: "1px solid " + t.negative, color: t.negative }}>{error}</div>;
  }

  const tMesi = resp?.tabelle?.find((x) => x.titolo.toLowerCase().includes("mese")) ?? resp?.tabelle?.[0];
  const tStag = resp?.tabelle?.find((x) => x.titolo.toLowerCase().includes("stagioni")) ?? resp?.tabelle?.[1];
  if (!tMesi || !tMesi.dati.length) {
    return (
      <div className="my-8 p-6 text-center text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
        Nessuna vendita con data valida nel periodo selezionato.
      </div>
    );
  }

  const colonne = tMesi.colonne;
  const serie = colonne.filter((c) => c.startsWith("Fatturato Netto"));
  const rows = tMesi.dati;
  const sum = (col?: string) =>
    col ? rows.reduce((s, r) => s + (Number(r[col]) || 0), 0) : 0;

  const cur = serie[0];
  const old = serie[1];
  const ordiniCol = colonne.find((c) => c.startsWith("Ordini "));
  const paiaCol = colonne.find((c) => c.startsWith("Paia Nette "));
  const resoCol = colonne.find((c) => c.startsWith("% Reso"));
  const resoMedio = resoCol && rows.length
    ? rows.reduce((s, r) => s + (Number(r[resoCol]) || 0), 0) / rows.length
    : 0;
  const varFatt = old && sum(old) !== 0 ? sum(cur) / sum(old) - 1 : undefined;

  return (
    <div>
      <div className="flex gap-3.5 flex-wrap">
        <KpiCard label="Fatturato netto" value={fmtEUR(sum(cur))}
                  delta={varFatt !== undefined ? fmtVar(varFatt) : undefined} deltaGood={varFatt !== undefined ? varFatt >= 0 : true} />
        <KpiCard label="Ordini" value={fmtInt(sum(ordiniCol))} />
        <KpiCard label="Paia nette" value={fmtInt(sum(paiaCol))} />
        <KpiCard label="% Reso (media mesi)" value={fmtPct(resoMedio)} />
      </div>

      <Section title="Andamento mese per mese"
        caption="Finestra mobile dal mese di inizio periodo al mese finale. Confronto posizionale: stesso mese di anno\u22121 (e anno\u22122 se attivo).">
        <div className="rounded-xl px-3 py-2" style={{ border: "1px solid " + t.border, background: t.surface }}>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={rows} margin={{ top: 20, right: 16, left: 4, bottom: 4 }}>
              <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="Mese" stroke={t.muted} tickLine={false} axisLine={{ stroke: t.grid }} tick={{ fontSize: 12 }} />
              <YAxis stroke={t.muted} tickLine={false} axisLine={false} tick={{ fontSize: 11 }}
                     tickFormatter={(v: number) => (v / 1000).toFixed(0) + "k"} width={44} />
              <Tooltip
                contentStyle={{ background: t.card, border: "1px solid " + t.border, borderRadius: 12, color: t.text }}
                formatter={(v: any) => fmtEUR(Number(v))}
                labelStyle={{ color: t.text, fontWeight: 700 }} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} iconType="circle" iconSize={8} />
              {serie.map((s, i) => (
                <Line key={s} type="monotone" dataKey={s} stroke={SERIES[i % SERIES.length]}
                      strokeWidth={i === 0 ? 2.5 : 2} dot={{ r: i === 0 ? 3 : 2.5 }}
                      strokeDasharray={i === 2 ? "6 3" : undefined} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4">
          <DataTable columns={colonne} rows={rows} />
        </div>
      </Section>

      {tStag && (
        <Section title="Statistiche stagioni SS/FW"
          caption="SS = 01 marzo \u2192 31 agosto \u00b7 FW = 01 settembre \u2192 28-29 febbraio. Confronto per posizione.">
          <DataTable columns={tStag.colonne} rows={tStag.dati} />
        </Section>
      )}
    </div>
  );
}