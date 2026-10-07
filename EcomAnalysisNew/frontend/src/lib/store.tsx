import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { getReport, getVenditeGroup, ReportResp, VenditeResp, UnauthorizedError } from "./api";

/* Cache unica dei dati. All'avvio e a ogni cambio periodo il provider mette
   in coda TUTTO il menu del periodo; la coda gira con al massimo 3 richieste
   in parallelo (non affoga la API sulla VPS) e NON si ferma mai cambiando
   pagina: il provider vive nella shell, non nelle pagine. Ogni combinazione
   (report, periodo, confronti) si scarica una sola volta e resta in memoria
   finche' il periodo non cambia. Il progresso (pending/done/total) e' visibile
   dalla barra in alto tramite useProgress. */

type Entry =
  | { s: "loading" }
  | { s: "ok"; data: unknown }
  | { s: "err"; msg: string; unauth: boolean };

interface DataCtxT {
  map: Record<string, Entry>;
  ensure: (key: string, fetcher: () => Promise<unknown>) => void;
  retry: (key: string, fetcher: () => Promise<unknown>) => void;
  pending: number;
  done: number;
  total: number;
}

const DataCtx = createContext<DataCtxT>({ map: {}, ensure: () => {}, retry: () => {}, pending: 0, done: 0, total: 0 });

const MAX_PARALLEL = 3;

function keyReport(tipo: string, da: string, a: string, confronti: number,
                   extra?: Record<string, string | number>): string {
  return "r|" + tipo + "|" + da + "|" + a + "|" + confronti + "|" + (extra ? JSON.stringify(extra) : "{}");
}

export function DataProvider({ da, a, confronti, children }: {
  da: string; a: string; confronti: number; children: React.ReactNode;
}) {
  const [map, setMap] = useState<Record<string, Entry>>({});
  const [stats, setStats] = useState({ pending: 0, done: 0, total: 0 });
  const doneSet = useRef<Set<string>>(new Set());
  const queued = useRef<Set<string>>(new Set());
  const queue = useRef<Array<{ key: string; fetcher: () => Promise<unknown> }>>([]);
  const active = useRef(0);
  const counters = useRef({ started: 0, finished: 0 });

  const bump = () => setStats({
    pending: counters.current.started - counters.current.finished,
    done: counters.current.finished,
    total: counters.current.started,
  });

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
          setMap((m) => ({ ...m, [job.key]: { s: "err", msg: String((e as Error)?.message ?? e),
                                              unauth: e instanceof UnauthorizedError } }));
        })
        .finally(() => {
          active.current--;
          counters.current.finished++;
          bump();
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
    counters.current.started++;
    bump();
    setMap((m) => ({ ...m, [key]: { s: "loading" } }));
    queue.current.push({ key, fetcher });
    pump();
  };

  const ensure = (key: string, fetcher: () => Promise<unknown>) => enqueue(key, fetcher, false);
  const retry = (key: string, fetcher: () => Promise<unknown>) => enqueue(key, fetcher, true);

  /* caricamento unico del periodo: tutto il menu, in coda, non si ferma mai */
  useEffect(() => {
    const c = confronti;
    ensure(keyReport("mensile", da, a, c), () => getReport("mensile", da, a, c));
    ensure(keyReport("dashboard", da, a, c, { top: 100 }), () => getReport("dashboard", da, a, c, { top: 100 }));
    ensure(keyReport("nazioni", da, a, c), () => getReport("nazioni", da, a, c));
    ensure(keyReport("y2y_collezioni", da, a, Math.max(c, 1)), () => getReport("y2y_collezioni", da, a, Math.max(c, 1)));
    for (const g of ["mkp", "nazione", "brand", "genere", "taglia", "acquirente"]) {
      ensure("v|" + g + "|" + da + "|" + a, () => getVenditeGroup(da, a, g));
    }
  }, [da, a, confronti]);

  return (
    <DataCtx.Provider value={{ map, ensure, retry, pending: stats.pending, done: stats.done, total: stats.total }}>
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

/* Progresso del caricamento del periodo, per la barra in alto. */
export function useProgress(): { pending: number; done: number; total: number } {
  const { pending, done, total } = useContext(DataCtx);
  return { pending, done, total };
}
