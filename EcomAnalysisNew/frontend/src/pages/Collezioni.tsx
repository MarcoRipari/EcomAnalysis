import React, { useEffect, useState } from "react";
import { getReport, ReportResp, UnauthorizedError } from "../lib/api";
import { Section, DataTable, useTheme } from "../components/ui";

/* Analisi brand/collezioni dal report y2y_collezioni: tabella gerarchica
   Brand + Collezione Originale, dettaglio per marketplace e per nazione.
   I report y2y_* sono comparativi per natura: il confronto anno-1 e' sempre
   attivo, l'anno-2 arriva dal selettore globale (confronti=2). Tutto guidato
   dai titoli e dai nomi colonna dell'API: zero hardcoding. */

export default function Collezioni({ da, a, confronti }: { da: string; a: string; confronti: number }) {
  const { t } = useTheme();
  const [resp, setResp] = useState<ReportResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [authErr, setAuthErr] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const c = confronti < 1 ? 1 : confronti; /* y2y_* richiede almeno il confronto anno-1 */

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setAuthErr(false);
    setError(null);
    getReport("y2y_collezioni", da, a, c)
      .then((r) => { if (alive) { setResp(r); setLoading(false); } })
      .catch((e) => {
        if (!alive) return;
        if (e instanceof UnauthorizedError) setAuthErr(true);
        else setError(String(e.message ?? e));
        setLoading(false);
      });
    return () => { alive = false; };
  }, [da, a, c]);

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
  if (!resp || !resp.tabelle.length) {
    return (
      <div className="text-center py-16 text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
        Nessuna collezione nel periodo selezionato.
      </div>
    );
  }

  return (
    <div>
      {resp.tabelle.map((tb, i) => (
        <Section key={tb.titolo + " " + i} title={tb.titolo}>
          <DataTable columns={tb.colonne} rows={tb.dati} />
        </Section>
      ))}
    </div>
  );
}