import React, { createContext, useContext, useEffect, useState } from "react";

/* Design system EcomAnalysis: token dark/light (LIGHT e' il default),
   formattatori italiani, componenti base. Layout ispirato a Berry free react
   admin (codedthemes) e react-material-admin (flatlogic): sidebar con voci
   tonde, header bar, card con ombra soffusa e radius 12, stat card con
   truncation. Nessun codice copiato dai template: solo il linguaggio visivo. */

export interface ThemeTokens {
  bg: string; surface: string; card: string; border: string;
  text: string; muted: string; accent: string; accentSoft: string;
  positive: string; negative: string; grid: string; shadow: string;
}

const DARK: ThemeTokens = {
  bg: "#0B1220", surface: "#111A2C", card: "#16233A", border: "#22304A",
  text: "#E7EEF8", muted: "#93A1B8", accent: "#14B8A6", accentSoft: "rgba(20,184,166,0.14)",
  positive: "#34D399", negative: "#F87171", grid: "rgba(147,161,184,0.15)",
  shadow: "0 2px 12px rgba(2,6,23,0.45)",
};

const LIGHT: ThemeTokens = {
  bg: "#F5F7FA", surface: "#FFFFFF", card: "#FFFFFF", border: "#E2E8F0",
  text: "#0F1B2D", muted: "#5B6B82", accent: "#0D9488", accentSoft: "rgba(13,148,136,0.10)",
  positive: "#059669", negative: "#DC2626", grid: "rgba(15,27,45,0.08)",
  shadow: "0 2px 12px rgba(15,27,45,0.08)",
};

const SERIES = ["#14B8A6", "#3B82F6", "#F59E0B"];
export { SERIES };

interface ThemeCtx { mode: "dark" | "light"; t: ThemeTokens; toggle: () => void; }
const ThemeContext = createContext<ThemeCtx>({ mode: "light", t: LIGHT, toggle: () => {} });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<"dark" | "light">(() =>
    localStorage.getItem("ea_theme") === "dark" ? "dark" : "light");
  useEffect(() => { localStorage.setItem("ea_theme", mode); }, [mode]);
  const toggle = () => setMode(mode === "dark" ? "light" : "dark");
  return (
    <ThemeContext.Provider value={{ mode, t: mode === "dark" ? DARK : LIGHT, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeCtx {
  return useContext(ThemeContext);
}

/* ---------- formattatori (coerenti con api/main.py, output csv/md) ---------- */
const it = (v: number, d: number) =>
  v.toLocaleString("it-IT", { minimumFractionDigits: d, maximumFractionDigits: d });

export const fmtEUR = (v: number) => it(v, 2) + " \u20ac";
export const fmtInt = (v: number) => it(v, 0);
export const fmtPct = (v: number) => it(v * 100, 1) + "%";
export const fmtVar = (v: number) => (v >= 0 ? "+" : "-") + it(Math.abs(v * 100), 1) + "%";

function tipoColonna(col: string): string {
  const n = col.toLowerCase();
  if (n.includes("%")) return n.startsWith("var") ? "var" : "percent";
  if (n.includes("ordini") || n.includes("righe") || n.includes("paia")) return "intero";
  if (n.includes("fatt") || n.includes("netto") || n.includes("lordo") || n.includes("scontrino") || n.includes("margine")) return "valuta";
  return "testo";
}

export function isVarCol(col: string): boolean {
  return tipoColonna(col) === "var";
}

export function fmtCell(col: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v !== "number") return String(v);
  const t = tipoColonna(col);
  if (t === "valuta") return fmtEUR(v);
  if (t === "intero") return fmtInt(v);
  if (t === "percent") return fmtPct(v);
  if (t === "var") return fmtVar(v);
  return v.toLocaleString("it-IT");
}

/* ---------- componenti ---------- */
export function Panel({ children, style, className }: { children: React.ReactNode; style?: React.CSSProperties; className?: string }) {
  const { t } = useTheme();
  return (
    <div className={"rounded-xl " + (className ?? "")}
         style={{ background: t.surface, border: "1px solid " + t.border, boxShadow: t.shadow, ...style }}>
      {children}
    </div>
  );
}

export function Section({ title, caption, children }: { title: string; caption?: string; children: React.ReactNode }) {
  const { t } = useTheme();
  return (
    <div className="mt-8">
      <div className="flex items-center gap-2.5">
        <div style={{ width: 4, height: 18, borderRadius: 2, background: t.accent }} />
        <h2 className="text-[15px] font-bold tracking-wide" style={{ color: t.text }}>{title}</h2>
      </div>
      {caption ? (
        <p className="text-xs mt-1.5 mb-3" style={{ color: t.muted }}>{caption}</p>
      ) : (
        <div className="mb-3" />
      )}
      {children}
    </div>
  );
}

export function Loading() {
  const { t } = useTheme();
  return <div className="py-16 text-center text-sm" style={{ color: t.muted }}>Caricamento...</div>;
}

export function LoadErr({ auth, error, onRetry }: { auth: boolean; error?: string | null; onRetry?: () => void }) {
  const { t } = useTheme();
  return (
    <div className="my-8 p-5 rounded-xl text-sm" style={{ border: "1px solid " + t.negative, color: t.text, background: t.card, boxShadow: t.shadow }}>
      <p className="font-bold" style={{ color: t.negative }}>{auth ? "Autenticazione non valida" : "Errore di caricamento"}</p>
      <p className="mt-1.5 text-xs" style={{ color: t.muted }}>
        {auth ? "Sessione scaduta o credenziali non valide: esci e accedi di nuovo." : (error ?? "Riprova piu' tardi.")}
      </p>
      {!auth && onRetry && (
        <button onClick={onRetry} className="mt-3 px-3 py-1.5 rounded-lg text-xs font-semibold"
                style={{ border: "1px solid " + t.border, color: t.accent, background: t.card }}>
          Riprova
        </button>
      )}
    </div>
  );
}

/* Indicatore di stato del caricamento del periodo per la barra in alto.
   SEMPRE visibile accanto al selettore del periodo:
   - in caricamento: spinner + "Caricamento fatti/totale (restanti)";
   - coda completata: pallino verde + "Dati pronti". */
export function LoadIndicator({ done, total, pending }: { done: number; total: number; pending: number }) {
  const { t } = useTheme();
  const mancanti = Math.max(total - done, 0);
  if (pending > 0 || done < total) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg"
           style={{ border: "1px solid " + t.border, background: t.card }}
           title="Caricamento dei dati del periodo in corso: resta anche cambiando pagina">
        <div className="ea-spin" style={{ width: 13, height: 13, border: "2px solid " + t.border,
                                           borderTopColor: t.accent }} />
        <span className="text-[11px] font-semibold whitespace-nowrap" style={{ color: t.muted }}>
          Caricamento {done}/{total}
        </span>
        <span className="text-[11px] font-semibold whitespace-nowrap" style={{ color: t.accent }}>
          {"\u2013 mancano " + mancanti}
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg"
         style={{ border: "1px solid " + t.border, background: t.card }}
         title="Tutti i dati del periodo sono in cache: la navigazione e' istantanea">
      <div style={{ width: 8, height: 8, borderRadius: 9999, background: t.positive }} />
      <span className="text-[11px] font-semibold whitespace-nowrap" style={{ color: t.muted }}>
        Dati pronti
      </span>
    </div>
  );
}

export function KpiCard({ label, value, delta, deltaGood }: {
  label: string; value: string; delta?: string; deltaGood?: boolean;
}) {
  const { t } = useTheme();
  return (
    <Panel className="flex-1 min-w-0 px-4 py-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.06em] truncate" title={label}
         style={{ color: t.muted }}>{label}</p>
      <p className="text-2xl font-extrabold mt-1 tabular-nums truncate" title={value}
         style={{ color: t.text }}>{value}</p>
      {delta !== undefined && (
        <p className="text-xs font-semibold mt-1" style={{ color: deltaGood ? t.positive : t.negative }}>{delta}</p>
      )}
    </Panel>
  );
}

function ImageModal({ src, title, onClose }: { src: string; title: string; onClose: () => void }) {
  const { t } = useTheme();
  return (
    <div onClick={onClose}
         style={{ position: "fixed", inset: 0, background: "rgba(2,6,23,0.7)", display: "flex",
                  alignItems: "center", justifyContent: "center", zIndex: 50, cursor: "zoom-out" }}>
      <div onClick={(e) => e.stopPropagation()} className="rounded-xl p-4 max-w-[80vw]"
           style={{ background: t.surface, border: "1px solid " + t.border, boxShadow: t.shadow }}>
        <img src={src} alt={title} style={{ maxWidth: "72vw", maxHeight: "64vh", borderRadius: 8 }} />
        <p className="text-xs mt-3 text-center" style={{ color: t.muted }}>{title}</p>
      </div>
    </div>
  );
}

/* Tabella Top Articoli: thumbnail a sinistra della riga, click = zoom. */
export function TopArticoliTable({ columns, rows }: { columns: string[]; rows: Array<Record<string, unknown>> }) {
  const { t } = useTheme();
  const [zoom, setZoom] = useState<{ src: string; title: string } | null>(null);
  const imgCol = columns.find((c) => /foto|image|url|img/i.test(c));
  const cols = columns.filter((c) => c !== imgCol);
  const titleCol = cols[0];

  if (!rows.length) {
    return (
      <div className="text-center py-10 text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
        Nessun articolo nel periodo/perimetro selezionato.
      </div>
    );
  }
  return (
    <div>
      <Panel className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr>
                <th className="w-16 px-4 py-2.5" />
                {cols.map((c) => (
                  <th key={c} className="text-left px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.05em] whitespace-nowrap"
                      style={{ color: t.muted, borderBottom: "1px solid " + t.border }}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const src = imgCol ? String(r[imgCol] ?? "") : "";
                const titolo = titleCol ? String(r[titleCol] ?? "") : "";
                return (
                  <tr key={i} style={{ borderTop: i === 0 ? "none" : "1px solid " + t.border }}>
                    <td className="px-4 py-2">
                      {src && (
                        <img src={src} alt={titolo} loading="lazy" onClick={() => setZoom({ src, title: titolo })}
                             style={{ width: 44, height: 44, borderRadius: 10, objectFit: "cover",
                                      cursor: "zoom-in", border: "1px solid " + t.border,
                                      display: "block", background: t.card }} />
                      )}
                    </td>
                    {cols.map((c) => {
                      const raw = r[c];
                      const neg = isVarCol(c) && typeof raw === "number" && raw < 0;
                      const isTitle = c === titleCol;
                      return (
                        <td key={c} className="px-4 py-2.5 whitespace-nowrap tabular-nums"
                            title={isTitle ? String(raw) : undefined}
                            style={{ color: neg ? t.negative : t.text,
                                     ...(isTitle ? { maxWidth: 340, overflow: "hidden", textOverflow: "ellipsis" } : null) }}>
                          {fmtCell(c, raw)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      {zoom && <ImageModal src={zoom.src} title={zoom.title} onClose={() => setZoom(null)} />}
    </div>
  );
}

export function DataTable({ columns, rows }: { columns: string[]; rows: Array<Record<string, unknown>> }) {
  const { t } = useTheme();
  if (!rows.length) {
    return (
      <div className="text-center py-10 text-sm rounded-xl" style={{ border: "1px dashed " + t.border, color: t.muted }}>
        Nessun dato nel periodo/perimetro selezionato.
      </div>
    );
  }
  return (
    <Panel className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} className="text-left px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.05em] whitespace-nowrap"
                    style={{ color: t.muted, borderBottom: "1px solid " + t.border }}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} style={{ borderTop: i === 0 ? "none" : "1px solid " + t.border }}>
                {columns.map((c, ci) => {
                  const raw = r[c];
                  const neg = isVarCol(c) && typeof raw === "number" && raw < 0;
                  const long = ci === 0 && typeof raw === "string" && raw.length > 36;
                  return (
                    <td key={c} className="px-4 py-2.5 whitespace-nowrap tabular-nums"
                        title={long ? String(raw) : undefined}
                        style={{ color: neg ? t.negative : t.text,
                                 ...(long ? { maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" } : null) }}>
                      {fmtCell(c, raw)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
