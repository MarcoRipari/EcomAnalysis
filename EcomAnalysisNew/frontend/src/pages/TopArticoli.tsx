import React from "react";
import { useReport } from "../lib/store";
import { Section, TopArticoliTable, Loading, LoadErr, useTheme } from "../components/ui";

/* Classifica articoli del periodo (livello SKU13) dal report tipo=dashboard
   con top=100. Dati dalla cache unica: nessun fetch diretto. */

export default function TopArticoli({ da, a, confronti }: { da: string; a: string; confronti: number }) {
  const { t } = useTheme();
  const r = useReport("dashboard", da, a, confronti, { top: 100 });
  if (r.loading) return <Loading />;
  if (r.authErr) return <LoadErr auth />;
  if (r.error) return <LoadErr auth={false} error={r.error} />;

  const tabs = (r.data?.tabelle ?? []).filter((x) => x.titolo.toLowerCase().indexOf("top articoli") >= 0);
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
