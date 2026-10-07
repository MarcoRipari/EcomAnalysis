import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { getReport, getVenditeGroup, ReportResp, VenditeResp, UnauthorizedError } from "./api";

/* Cache unica dei dati. All'avvio e a ogni cambio periodo il provider mette
   in coda TUTTI i lavori del periodo (jobsFor); la coda gira con al massimo 3
   richieste in parallelo (non affoga la API sulla VPS) e NON si ferma mai
   cambiando pagina: il provider vive nella shell e avvolge ANCHE la barra in
   alto, quindi l'indicatore legge la stessa mappa delle pagine. Ogni chiave
   (report, periodo, confronti) si scarica una sola volta e resta in memoria
   finche' il periodo non cambia. useProgress deriva lo stato dei lavori
   DIRETTAMENTE dalla mappa (nessun contatore separato): "pronti" solo quando
   tutte le voci sono ok. Ogni pagina renderizza con i SUOI dati non appena
   pronti, anche se gli altri lavori sono ancora in coda. */

type Entry =
  | { s: "loading" }
  | { s: "ok"; data: unknown }
  | { s: "err"; msg: string; unauth: boolean };

export type JobStatus = "loading" | "ok" | "err";

export interface JobInfo {
  id: string;
  label: string;
  status: JobStatus;
}

interface DataCtxT {
  map: Record<string, Entry>;
  ensure: (key: string, fetcher: () => Promise<unknown>) => void;
  retry: (key: string, fetcher: () => Promise<unknown>) => void;
}

const DataCtx = createContext<DataCtxT>({ map: {}, ensure: () => {}, retry: () => {} });

const MAX_PARALLEL = 3;

function keyReport(tipo: string, da: string, a: string, confronti: number,
                   extra?: Record<string, string | number>): string {
  return "r|" + tipo + "|" + da + "|" + a + "|" + confronti + "|" + (extra ? JSON.stringify(extra) : "{}");
}

interface JobDef {
  id: string;
  label: string;
  key: string;
  fetcher: () => Promise<unknown>;
}

/* Lavori del periodo: sono ESATTAMENTE le chiavi che usano le pagine, quindi
   indicatore e pagine condividono la stessa fonte di verita'. */
export function jobsFor(da: string, a: string, confronti: number): JobDef[] {
  const c = confronti;
  const cc = Math.max(c, 1);
  const vendite: Array<[string, string]> = [
    ["mkp", "Vendite Marketplace"],
    ["nazione", "Vendite Nazione"],
    ["brand", "Vendite Brand"],
    ["genere", "Vendite Genere"],
    ["taglia", "Vendite Taglia"],
    ["acquirente", "Vendite Acquirente"],
  ];
  return [
    { id: "mensile", label: "Mensile",
      key: keyReport("mensile", da, a, c),
      fetcher: () => getReport("mensile", da, a, c) },
    { id: "dashboard", label: "Dashboard",
      key: keyReport("dashboard", da, a, c, { top: 100 }),
      fetcher: () => getReport("dashboard", da, a, c, { top: 100 }) },
    { id: "nazioni", label: "Nazioni",
      key: keyReport("nazioni", da, a, c),
      fetcher: () => getReport("nazioni", da, a, c) },
    { id: "collezioni", label: "Collezioni",
      key: keyReport("y2y_collezioni", da, a, cc),
      fetcher: () => getReport("y2y_collezioni", da, a, cc) },
    ...vendite.map(([g, label]) => ({
      id: "v_" + g, label,
      key: "v|" + g + "|" + da + "|" + a,
      fetcher: () => getVenditeGroup(da, a, g),
    })),
  ];
}

export function DataProvider({ da, a, confronti, children }: {
  da: string; a: string; confronti: number; children: React.ReactNode;
}) {
  const [map, setMap] = useState<Record<string, Entry>>({});
  const doneSet = useRef<Set<string>>(new Set());
  const queued = useRef<Set<string>>(new Set());
  const queue = useRef<Array<{ key: string; fetcher: () => Promise<unknown> }>>([]);
  const active = useRef(0);

  const pump = () => {
    while (active.current < MAX_PARALLEL && queue.current.length > 0) {
      const job = queue.current.shift()!;
      queued.current.delete(job.key);
      active.current++;
      job.fetcher()
        .then((data) => {
          doneSet.current.add(job.key);
          setMap((m) => ({ ...m, [job.key]: { s: "ok", data } }));
        })
        .catch((e) => {
          doneSet.current.delete(job.key);
          setMap((m) => ({ ...m, [job.key]: { s: "err", msg: String((e as Error)?.message ?? e),
                                              unauth: e instanceof UnauthorizedError } }));
        })
        .finally(() => {
          active.current--;
          pump();
        });
    }
  };

  const enqueue = (key: string, fetcher: () => Promise<unknown>, force: boolean) => {
    const known = doneSet.current.has(key) || queued.current.has(key);
    if (!force && known) return;
    if (doneSet.current.has(key)) doneSet.current.delete(key);
    queue.current = queue.current.filter((j) => j.key !== key);
    queued.current.add(key);
    setMap((m) => ({ ...m, [key]: { s: "loading" } }));
    queue.current.push({ key, fetcher });
    pump();
  };

  const ensure = (key: string, fetcher: () => Promise<unknown>) => enqueue(key, fetcher, false);
  const retry = (key: string, fetcher: () => Promise<unknown>) => enqueue(key, fetcher, true);

  /* caricamento unico del periodo: tutti i lavori, in coda, mai interrotto
     dal cambio pagina; riparte SOLO al cambio periodo/confronti */
  useEffect(() => {
    for (const job of jobsFor(da, a, confronti)) {
      ensure(job.key, job.fetcher);
    }
  }, [da, a, confronti]);

  return (
    <DataCtx.Provider value={{ map, ensure, retry }}>
      {children}
    </DataCtx.Provider>
  );
}

export interface Cached<T> {
  data?: T;
  loading: boolean;
  authErr: boolean;
  error: string | null;
  retry: () => void;
}

function pick<T>(e: Entry | undefined, doRetry: () => void): Cached<T> {
  if (!e) return { loading: true, authErr: false, error: null, retry: doRetry };
  if (e.s === "ok") return { data: e.data as T, loading: false, authErr: false, error: null, retry: doRetry };
  if (e.s === "err") return { loading: false, authErr: e.unauth, error: e.msg, retry: doRetry };
  return { loading: true, authErr: false, error: null, retry: doRetry };
}

export function useReport(tipo: string, da: string, a: string, confronti: number,
                          extra?: Record<string, string | number>): Cached<ReportResp> {
  const { map, ensure, retry } = useContext(DataCtx);
  const key = keyReport(tipo, da, a, confronti, extra);
  useEffect(() => {
    ensure(key, () => getReport(tipo, da, a, confronti, extra));
  }, [key]);
  return pick<ReportResp>(map[key], () => retry(key, () => getReport(tipo, da, a, confronti, extra)));
}

export function useVendite(da: string, a: string, group: string): Cached<VenditeResp> {
  const { map, ensure, retry } = useContext(DataCtx);
  const key = "v|" + group + "|" + da + "|" + a;
  useEffect(() => {
    ensure(key, () => getVenditeGroup(da, a, group));
  }, [key]);
  return pick<VenditeResp>(map[key], () => retry(key, () => getVenditeGroup(da, a, group)));
}

export interface Progress {
  jobs: JobInfo[];
  loading: number;
  ok: number;
  err: number;
  total: number;
  ready: boolean;
}

/* Stato dei lavori del periodo, DERIVATO dalla stessa mappa che usano le
   pagine: impossibile che l'indicatore dica "pronti" con pagine in caricamento. */
export function useProgress(da: string, a: string, confronti: number): Progress {
  const { map } = useContext(DataCtx);
  const jobs: JobInfo[] = jobsFor(da, a, confronti).map((j) => {
    const e = map[j.key];
    const status: JobStatus = !e ? "loading" : e.s === "ok" ? "ok" : e.s === "err" ? "err" : "loading";
    return { id: j.id, label: j.label, status };
  });
  const loading = jobs.filter((j) => j.status === "loading").length;
  const ok = jobs.filter((j) => j.status === "ok").length;
  const err = jobs.filter((j) => j.status === "err").length;
  return { jobs, loading, ok, err, total: jobs.length, ready: loading === 0 && err === 0 };
}
