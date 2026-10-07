import React, { useEffect, useState } from "react";
import { Routes, Route, NavLink, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ThemeProvider, useTheme, LoadIndicator } from "./components/ui";
import { useAuth, AuthProvider } from "./lib/auth";
import { DataProvider, useProgress } from "./lib/store";
import Dashboard from "./pages/Dashboard";
import Y2Y from "./pages/Y2Y";
import Collezioni from "./pages/Collezioni";
import Nazioni from "./pages/Nazioni";
import TopArticoli from "./pages/TopArticoli";
import Ordini from "./pages/Ordini";
import Account from "./pages/Account";
import Login from "./pages/Login";

/* Shell ispirata a Berry/Material Admin. Il periodo e GLOBALE (default: anno
   fiscale 01/11 -> 31/10). Il caricamento dei dati del periodo parte UNA volta
   e continua in background anche cambiando pagina: l'indicatore nella barra
   in alto (a sinistra del selettore periodo) mostra l'avanzamento. Per gli
   utenti Supabase senza 2FA attiva compare il banner che porta all'Account. */

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/y2y", label: "Y2Y Generale" },
  { to: "/collezioni", label: "Collezioni" },
  { to: "/nazioni", label: "Nazioni" },
  { to: "/articoli", label: "Top Articoli" },
  { to: "/ordini", label: "Ordini" },
  { to: "/account", label: "Account" },
];

const TITOLI: Record<string, { title: string; sub: string }> = {
  "/": { title: "Dashboard", sub: "Quadro d insieme sul periodo selezionato" },
  "/y2y": { title: "Comparativa Year-over-Year", sub: "Confronti posizionali anno\u22121 / anno\u22122" },
  "/collezioni": { title: "Collezioni", sub: "Analisi gerarchica brand e collezioni con confronto anno-1" },
  "/nazioni": { title: "Nazioni", sub: "KPI per nazione e share brand per mercato" },
  "/articoli": { title: "Top Articoli", sub: "Classifica articoli del periodo con foto" },
  "/ordini": { title: "Ordini", sub: "Ordini aggregati per dimensione di analisi" },
  "/account": { title: "Account", sub: "Sessione, 2FA, copertura dati e ultimi caricamenti" },
};

function annoFiscaleCorrente(): number {
  const n = new Date();
  return n.getMonth() + 1 >= 11 ? n.getFullYear() + 1 : n.getFullYear();
}

function periodoDefault(): { da: string; a: string } {
  const chiusura = annoFiscaleCorrente();
  return { da: chiusura - 1 + "-11-01", a: chiusura + "-10-31" };
}

function HeaderBar({ da, a, onOpen }: { da: string; a: string; onOpen: () => void }) {
  const { t } = useTheme();
  const prog = useProgress();
  const pill = da + " \u2192 " + a;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {prog.pending > 0 && <LoadIndicator done={prog.done} total={prog.total} />}
      <div className="flex-1 min-w-0" />
      <button onClick={onOpen}
              className="px-3.5 py-2 rounded-lg text-xs font-semibold"
              style={{ border: "1px solid " + t.border, color: t.text, background: t.card }}>
        {pill} {"\u25BE"}
      </button>
    </div>
  );
}

function MfaBanner() {
  const { t } = useTheme();
  const navigate = useNavigate();
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 mb-4 rounded-xl"
         style={{ border: "1px solid " + t.accent, background: t.accentSoft }}>
      <p className="text-xs font-semibold" style={{ color: t.text }}>
        Attiva l'autenticazione a due fattori (2FA) per proteggere il tuo account: e' obbligatoria.
      </p>
      <button onClick={() => navigate("/account")}
              className="px-3 py-1.5 rounded-lg text-xs font-bold"
              style={{ background: t.accent, color: "#FFFFFF" }}>
        Attiva ora
      </button>
    </div>
  );
}

function Shell() {
  const { mode, t, toggle } = useTheme();
  const { me, email, logout, mfaPending } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const def = periodoDefault();
  const [da, setDa] = useState(() => localStorage.getItem("ea_da") ?? def.da);
  const [a, setA] = useState(() => localStorage.getItem("ea_a") ?? def.a);
  const [confronti, setConfronti] = useState(() => Number(localStorage.getItem("ea_confronti") ?? 1));
  const [periodoOpen, setPeriodoOpen] = useState(false);

  useEffect(() => { document.documentElement.setAttribute("data-theme", mode); }, [mode]);
  useEffect(() => { localStorage.setItem("ea_da", da); }, [da]);
  useEffect(() => { localStorage.setItem("ea_a", a); }, [a]);
  useEffect(() => { localStorage.setItem("ea_confronti", String(confronti)); }, [confronti]);

  /* primo accesso senza 2FA: porta alla pagina Account per l'attivazione */
  useEffect(() => {
    if (mfaPending && location.pathname !== "/account") navigate("/account");
  }, [mfaPending]);

  const inputStyle = {
    background: t.card, color: t.text, border: "1px solid " + t.border,
    borderRadius: 8, padding: "6px 10px", fontSize: 12,
  } as React.CSSProperties;

  const page = TITOLI[location.pathname] ?? TITOLI["/"];
  const utente = me?.nome ?? email ?? "Utente";

  return (
    <div className="flex min-h-screen" style={{ background: t.bg, color: t.text }}>
      <aside className="w-56 shrink-0 flex flex-col" style={{ background: t.surface, borderRight: "1px solid " + t.border }}>
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="w-9 h-9 rounded-xl flex items-center justify-center text-sm font-black"
               style={{ background: t.accentSoft, color: t.accent }}>EA</div>
          <div>
            <p className="text-sm font-bold leading-tight">EcomAnalysis</p>
            <p className="text-[10px]" style={{ color: t.muted }}>Retail Analytics</p>
          </div>
        </div>
        <nav className="flex-1 px-3 space-y-1">
          {NAV.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) =>
                "flex items-center px-3 py-2 rounded-lg text-[13px] font-medium transition-colors " +
                (isActive ? "font-semibold" : "")}
              style={({ isActive }) => ({
                color: isActive ? t.accent : t.muted,
                background: isActive ? t.accentSoft : "transparent",
              })}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-3 py-4 space-y-3" style={{ borderTop: "1px solid " + t.border }}>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold shrink-0"
                 style={{ background: t.accentSoft, color: t.accent }}>
              {utente.slice(0, 1).toUpperCase()}
            </div>
            <p className="text-xs font-semibold truncate flex-1 min-w-0" title={utente}>{utente}</p>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[11px]" style={{ color: t.muted }}>Tema</span>
            <button onClick={toggle} className="px-2.5 py-1.5 rounded-lg text-[11px] font-semibold"
                    style={{ border: "1px solid " + t.border, color: t.text, background: t.card }}>
              {mode === "dark" ? "Dark" : "Light"}
            </button>
          </div>
          <button onClick={logout}
                  className="w-full px-2.5 py-1.5 rounded-lg text-[11px] font-semibold"
                  style={{ border: "1px solid " + t.border, color: t.negative, background: t.card }}>
            Esci
          </button>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="px-8 py-4" style={{ background: t.surface, borderBottom: "1px solid " + t.border }}>
          <div className="mb-3">
            <h1 className="text-xl font-extrabold tracking-tight">{page.title}</h1>
            <p className="text-xs mt-0.5" style={{ color: t.muted }}>{page.sub}</p>
          </div>
          <HeaderBar da={da} a={a} onOpen={() => setPeriodoOpen(!periodoOpen)} />
        </header>
        {/* selettore periodo semi-nascosto */}
        {periodoOpen && (
          <div className="px-8 py-3 flex flex-wrap items-end gap-3"
               style={{ background: t.surface, borderBottom: "1px solid " + t.border }}>
            <label className="text-[11px]" style={{ color: t.muted }}>
              <span className="block mb-1">Dal</span>
              <input type="date" value={da} style={inputStyle} onChange={(e) => setDa(e.target.value)} />
            </label>
            <label className="text-[11px]" style={{ color: t.muted }}>
              <span className="block mb-1">Al</span>
              <input type="date" value={a} style={inputStyle} onChange={(e) => setA(e.target.value)} />
            </label>
            <label className="text-[11px]" style={{ color: t.muted }}>
              <span className="block mb-1">Confronti</span>
              <select value={confronti} style={inputStyle} onChange={(e) => setConfronti(Number(e.target.value))}>
                <option value={0}>Solo periodo</option>
                <option value={1}>{"+ anno\u22121"}</option>
                <option value={2}>{"+ anno\u22121 e anno\u22122"}</option>
              </select>
            </label>
            <button onClick={() => { setDa(def.da); setA(def.a); }}
                    className="text-[11px] px-2.5 py-1.5 rounded-lg font-semibold"
                    style={{ border: "1px solid " + t.border, color: t.accent, background: t.card }}>
              Anno fiscale corrente
            </button>
          </div>
        )}
        <main className="flex-1 px-8 py-6">
          {mfaPending && <MfaBanner />}
          <DataProvider da={da} a={a} confronti={confronti}>
            <Routes>
              <Route path="/" element={<Dashboard da={da} a={a} confronti={confronti} />} />
              <Route path="/y2y" element={<Y2Y da={da} a={a} confronti={confronti} />} />
              <Route path="/collezioni" element={<Collezioni da={da} a={a} confronti={confronti} />} />
              <Route path="/nazioni" element={<Nazioni da={da} a={a} confronti={confronti} />} />
              <Route path="/articoli" element={<TopArticoli da={da} a={a} confronti={confronti} />} />
              <Route path="/ordini" element={<Ordini da={da} a={a} />} />
              <Route path="/account" element={<Account />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </DataProvider>
        </main>
      </div>
    </div>
  );
}

function Root() {
  const { t } = useTheme();
  const { ready, authed } = useAuth();
  if (!ready) {
    return <div className="min-h-screen flex items-center justify-center text-sm" style={{ color: t.muted }}>Caricamento...</div>;
  }
  if (!authed) return <Login />;
  return <Shell />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Root />
      </AuthProvider>
    </ThemeProvider>
  );
}
