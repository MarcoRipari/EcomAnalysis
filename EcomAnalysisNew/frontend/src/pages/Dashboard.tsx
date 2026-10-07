import React, { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { getMensileReport, getDashboardReport, ReportResp, UnauthorizedError } from "../lib/api";
import {
  Panel, Section, KpiCard, DataTable, TopArticoliTable,
  fmtEUR, fmtInt, fmtPct, fmtVar, SERIES, useTheme,
} from "../components/ui";

/* Dashboard del periodo (default: anno fiscale 01/11 -> 31/10 scelto nella shell).
   KPI + andamento mensile dal report tipo=mensile; tabelle e classifiche dal
   report tipo=dashboard; canali (Diretti/Zalando) letti dalla tabella Marketplace. */

export default function Dashboard({ da, a, confronti }: { da: string; a: string; confronti: number }) {
  const { t } = useTheme();
  const [mensile, setMensile] = useState<ReportResp | null>(null);
  const [dash, setDash] = useState<ReportResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [authErr, setAuthErr] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setAuthErr(false);
    setError(null);
    Promise.all([
      getMensileReport(da, a, confronti),
      getDashboardReport(da, a, confronti),
    ])
      .then(([m, d]) => { if (alive) { setMensile(m); setDash(d); setLoading(false); } })
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

  const tMesi = mensile?.tabelle?.find((x) => x.titolo.toLowerCase().includes("mese")) ?? mensile?.tabelle?.[0];
  const rows = tMesi?.dati ?? [];
  const colonne = tMesi?.colonne ?? [];
  const serie = colonne.filter((c) => c.startsWith("Fatturato Netto"));
  const sum = (col?: string) => (col ? rows.reduce((s, r) => s + (Number(r[col]) || 0), 0) : 0);
  const cur = serie[0];
  const old = serie[1];
  const ordiniCol = colonne.find((c) => c.startsWith("Ordini "));
  const paiaCol = colonne.find((c) => c.startsWith("Paia Nette "));
  const resoCol = colonne.find((c) => c.startsWith("% Reso"));
  const resoMedio = resoCol && rows.length ? rows.reduce((s, r) => s + (Number(r[resoCol]) || 0), 0) / rows.length : 0;
  const varFatt = old && sum(old) !== 0 ? sum(cur) / sum(old) - 1 : undefined;
  const totOrdini = sum(ordiniCol);
  const scontrino = totOrdini !== 0 ? sum(cur) / totOrdini : 0;

  // tabelle del report dashboard (current year: i titoli iniziano con la sezione corrente)
  const tab = (kw: string) => dash?.tabelle?.find((x) => x.titolo.toLowerCase().includes(kw));
  const tMkp = tab("marketplace");
  const tNaz = tab("nazioni");
  const tCol = tab("collezioni");
  const tTop = tab("top articoli");

  // canali dalla tabella marketplace
  const canale = (kw: string) =>
    tMkp?.dati.find((r) => Object.values(r).some((v) => String(v).toUpperCase().includes(kw)));
  const mkpFattCol = tMkp?.colonne.find((c) => c.toLowerCase().includes("fatturato"));
  const mkpNomeCol = tMkp?.colonne[0];
  const dir = canale("DIRETT");
  const zal = canale("ZALANDO");
  const val = (r: Record<string, unknown> | undefined, col?: string) =>
    r && col ? Number(r[col]) || 0 : 0;

  // top bar chart: marketplace e nazioni ordinati per fatturato (max 6)
  const topBar = (tb: typeof tMkp, n = 6) => {
    if (!tb || !mkpFattCol) return { rows: [], name: "", fatt: "" };
    const nameCol = tb.colonne[0];
    const fattCol = tb.colonne.find((c) => c.toLowerCase().includes("fatturato"));
    const out = tb.dati
      .map((r) => ({ name: String(r[nameCol] ?? ""), fatt: Number(r[fattCol ?? ""]) || 0 }))
      .sort((x, y) => y.fatt - x.fatt)
      .slice(0, n);
    return { rows: out, name: nameCol, fatt: fattCol ?? "" };
  };
  const topMkp = topBar(tMkp);
  const topNaz = topBar(tNaz);

  return (
    <div>
      {/* KPI principali */}
      <div className="flex gap-3.5 flex-wrap">
        <KpiCard label="Fatturato netto" value={fmtEUR(sum(cur))}
                  delta={varFatt !== undefined ? fmtVar(varFatt) : undefined}
                  deltaGood={varFatt !== undefined ? varFatt >= 0 : true} />
        <KpiCard label="Ordini" value={fmtInt(totOrdini)} />
        <KpiCard label="Paia nette" value={fmtInt(sum(paiaCol))} />
        <KpiCard label="% Reso (media mesi)" value={fmtPct(resoMedio)} />
        <KpiCard label="Scontrino medio" value={fmtEUR(scontrino)} />
      </div>

      {/* canali */}
      <div className="flex gap-3.5 flex-wrap mt-3.5">
        <KpiCard label="Canale Diretti \u2014 fatturato" value={fmtEUR(val(dir, mkpFattCol))} />
        <KpiCard label="Zalando (ZFS) \u2014 fatturato" value={fmtEUR(val(zal, mkpFattCol))} />
      </div>

      {/* riga: grafico mensile + top marketplace */}
      <div className="mt-8 grid grid-cols-1 xl:grid-cols-3 gap-3.5">
        <Panel className="xl:col-span-2 px-3 py-2">
          <p className="text-[13px] font-bold px-2 pt-2" style={{ color: t.text }}>Andamento mese per mese</p>
          <p className="text-[11px] px-2 pb-1" style={{ color: t.muted }}>
            {"Finestra mobile sul periodo selezionato \u00b7 confronto posizionale con lo stesso mese degli anni precedenti"}
          </p>
          {rows.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={rows} margin={{ top: 12, right: 16, left: 4, bottom: 4 }}>
                <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="Mese" stroke={t.muted} tickLine={false} axisLine={{ stroke: t.grid }} tick={{ fontSize: 11 }} />
                <YAxis stroke={t.muted} tickLine={false} axisLine={false} tick={{ fontSize: 11 }}
                       tickFormatter={(v: number) => (v / 1000).toFixed(0) + "k"} width={40} />
                <Tooltip
                  contentStyle={{ background: t.card, border: "1px solid " + t.border, borderRadius: 12, color: t.text }}
                  formatter={(v: any) => fmtEUR(Number(v))}
                  labelStyle={{ color: t.text, fontWeight: 700 }} />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 6 }} iconType="circle" iconSize={8} />
                {serie.map((s, i) => (
                  <Line key={s} type="monotone" dataKey={s} stroke={SERIES[i % SERIES.length]}
                        strokeWidth={i === 0 ? 2.5 : 2} dot={{ r: i === 0 ? 3 : 2.5 }}
                        strokeDasharray={i >= 2 ? "6 3" : undefined} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="py-10 text-center text-sm" style={{ color: t.muted }}>Nessun dato nel periodo.</div>
          )}
        </Panel>
        <Panel className="px-3 py-2">
          <p className="text-[13px] font-bold px-2 pt-2" style={{ color: t.text }}>Top Marketplace</p>
          <p className="text-[11px] px-2 pb-1" style={{ color: t.muted }}>Fatturato netto del periodo</p>
          {topMkp.rows.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={topMkp.rows} layout="vertical" margin={{ top: 8, right: 24, left: 8, bottom: 4 }}>
                <CartesianGrid stroke={t.grid} strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" stroke={t.muted} tickLine={false} axisLine={false} width={82}
                       tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: t.card, border: "1px solid " + t.border, borderRadius: 12, color: t.text }}
                  formatter={(v: any) => fmtEUR(Number(v))} cursor={{ fill: t.accentSoft }} />
                <Bar dataKey="fatt" fill={SERIES[0]} radius={[0, 6, 6, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="py-10 text-center text-sm" style={{ color: t.muted }}>Nessun dato.</div>
          )}
        </Panel>
      </div>

      {/* classifiche nazioni */}
      {topNaz.rows.length > 0 && (
        <Section title="Top Nazioni \u2014 fatturato netto">
          <Panel className="px-3 py-2">
            <ResponsiveContainer width="100%" height={Math.max(120, topNaz.rows.length * 34)}>
              <BarChart data={topNaz.rows} layout="vertical" margin={{ top: 8, right: 24, left: 8, bottom: 4 }}>
                <CartesianGrid stroke={t.grid} strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" stroke={t.muted} tickLine={false} axisLine={false} width={82}
                       tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: t.card, border: "1px solid " + t.border, borderRadius: 12, color: t.text }}
                  formatter={(v: any) => fmtEUR(Number(v))} cursor={{ fill: t.accentSoft }} />
                <Bar dataKey="fatt" fill={SERIES[1]} radius={[0, 6, 6, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        </Section>
      )}

      {/* tabelle */}
      {tMkp && (
        <Section title="Dettaglio Marketplace" caption="Ordinato per fatturato netto.">
          <DataTable columns={tMkp.colonne} rows={tMkp.dati} />
        </Section>
      )}
      {tNaz && (
        <Section title="Dettaglio Nazioni">
          <DataTable columns={tNaz.colonne} rows={tNaz.dati} />
        </Section>
      )}
      {tCol && (
        <Section title="Dettaglio Collezioni" caption="Ordinato per paia nette.">
          <DataTable columns={tCol.colonne} rows={tCol.dati} />
        </Section>
      )}
      {tTop && (
        <Section title="Top Articoli" caption="Thumbnail a sinistra \u00b7 clicca la foto per ingrandire.">
          <TopArticoliTable columns={tTop.colonne} rows={tTop.dati} />
        </Section>
      )}
    </div>
  );
}