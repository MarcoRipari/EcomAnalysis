import React, { useEffect, useState } from "react";
import { getReport, ReportResp, UnauthorizedError } from "../lib/api";
import { Section, TopArticoliTable, useTheme } from "../components/ui";

/* Classifica articoli del periodo (livello SKU13) dal report tipo=dashboard:
   si tengono solo le tabelle "Top Articoli" (una per anno in base ai
   confronti), con foto thumbnail espandibile con un click. top=100 e' il
   massimo consentito dall'API. */

export default function TopArticoli({ da, a, confronti }: { da: string; a: string; confronti: number }) {
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
    getReport("dashboard", da, a, confronti, { top: 100 })
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

  const tabs = (resp?.tabelle ?? []).filter((x) => x.titolo.toLowerCase().indexOf("top articoli") >= 0);
  if (!tabs.length) {
    return (
      <div className="text-center py-16 text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
        Nessun articolo nel periodo selezionato.
      </div>
    );
  }

  return (
    <div>
      {tabs.map((tb, i) => (
        <Section key={tb.titolo + " " + i} title={tb.titolo}>
          <TopArticoliTable columns={tb.colonne} rows={tb.dati} />
        </Section>
      ))}
    </div>
  );
}