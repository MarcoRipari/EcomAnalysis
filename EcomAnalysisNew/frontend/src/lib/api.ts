// Client API EcomAnalysis: stessa FastAPI di Streamlit, auth via X-API-Key.
// Il JSON resta numerico con nomi colonna gia rinominati (scelta di progetto).
// La chiave e' gestita dall AuthProvider (src/lib/auth.tsx): qui si legge
// localStorage (fonte di verita') e si ascolta l evento "ea_auth" per
// riflettere subito login/logout senza ricaricare la pagina.

export interface Tabella {
  titolo: string;
  righe: number;
  colonne: string[];
  dati: Array<Record<string, unknown>>;
}

export interface ReportResp {
  ok: boolean;
  parametri: Record<string, unknown>;
  tabelle: Tabella[];
}

const KEY_STORAGE = "ea_api_key";
const AUTH_EVENT = "ea_auth";

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) ?? "";
}

export function setApiKey(k: string): void {
  localStorage.setItem(KEY_STORAGE, k);
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function clearApiKey(): void {
  localStorage.removeItem(KEY_STORAGE);
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function onAuthChange(cb: () => void): () => void {
  window.addEventListener(AUTH_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(AUTH_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export class UnauthorizedError extends Error {}

export async function apiGet<T>(path: string, params: Record<string, string | number>): Promise<T> {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) q.set(k, String(v));
  const url = "/api" + path + "?" + q.toString();
  const headers: Record<string, string> = {};
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;
  const r = await fetch(url, { headers });
  if (r.status === 401 || r.status === 403) throw new UnauthorizedError("API key mancante o non valida");
  if (!r.ok) throw new Error("Errore API " + r.status);
  return (await r.json()) as T;
}

// Report "Mese per Mese": mesi del periodo scelto + stagioni SS/FW + confronti anno-1/anno-2.
export function getMensileReport(da: string, a: string, confronti: number): Promise<ReportResp> {
  return apiGet<ReportResp>("/v1/report", { tipo: "mensile", da, a, confronti, format: "json" });
}

// Report "Dashboard": tabelle annue Dettaglio Marketplace / Nazioni / Collezioni / Top Articoli.
export function getDashboardReport(da: string, a: string, confronti: number): Promise<ReportResp> {
  return apiGet<ReportResp>("/v1/report", { tipo: "dashboard", da, a, confronti, format: "json" });
}

// Report generico: tipo = dashboard | y2y_generale | y2y_collezioni | y2y_codici |
// taglie | resi | nazioni | unificato | mensile. extra: top, nazioni, dim, filtri.
export function getReport(tipo: string, da: string, a: string, confronti: number,
                          extra?: Record<string, string | number>): Promise<ReportResp> {
  return apiGet<ReportResp>("/v1/report", { tipo, da, a, confronti, format: "json", ...(extra ?? {}) });
}

export interface VenditeResp {
  ok: boolean;
  parametri: Record<string, unknown>;
  righe: number;
  dati: Array<Record<string, unknown>>;
}

// Vendite aggregate del periodo per dimensione:
// mkp | nazione | brand | genere | taglia | sku | acquirente.
export function getVenditeGroup(da: string, a: string, group: string): Promise<VenditeResp> {
  return apiGet<VenditeResp>("/v1/vendite", { da, a, level: "group", group, format: "json" });
}

export interface MeResp {
  ok: boolean;
  via: string;
  nome: string;
}

// Chi sta chiamando: tipo di credenziale e nome associato.
export function getMe(): Promise<MeResp> {
  return apiGet<MeResp>("/v1/me", {});
}

export interface PeriodiResp {
  ok: boolean;
  copertura: { da: string; a: string };
  righe: Record<string, number>;
  ultimiCaricamenti: Array<Record<string, unknown>>;
}

// Copertura dei dati nel DB, conteggi e ultimi caricamenti.
export function getPeriodi(): Promise<PeriodiResp> {
  return apiGet<PeriodiResp>("/v1/periodi", {});
}