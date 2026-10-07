import React from "react";
import { useReport } from "../lib/store";
import { Section, DataTable, Loading, LoadErr, useTheme } from "../components/ui";

/* Analisi brand/collezioni dal report y2y_collezioni (comparativo: confronto
   anno-1 sempre attivo, anno-2 dal selettore globale). Dati dalla cache. */

export default function Collezioni({ da, a, confronti }: { da: string; a: string; confronti: number }) {
  const { t } = useTheme();
  const c = confronti < 1 ? 1 : confronti;
  const r = useReport("y2y_collezioni", da, a, c);
  if (r.loading) return <Loading />;
  if (r.authErr) return <LoadErr auth />;
  if (r.error) return <LoadErr auth={false} error={r.error} />;
  const resp = r.data ?? null;
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
