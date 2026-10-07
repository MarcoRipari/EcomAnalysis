import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { getReport, getVenditeGroup, ReportResp, VenditeResp, UnauthorizedError } from "./api";

/* Cache unica dei dati: ogni combinazione (report, periodo, confronti, extra)
   si scarica UNA sola volta e viene riusata da tutte le pagine. All'avvio e a
   ogni cambio periodo il provider prefetcha tutto il menu in una sola raffica:
   navigare tra le pagine non costa piu' attese. */

type Entry =
  | { s: "loading" }
  | { s: "ok"; data: unknown }
  | { s: "err"; msg: string; unauth: boolean };

interface DataCtxT {
  map: Record<string, Entry>;
  ensure: (key: string, fetcher: () => Promise<unknown>) => void;
}

const DataCtx = createContext<DataCtxT>({ map: {}, ensure: () => {} });

function keyReport(tipo: string, da: string, a: string, confronti: number,
                   extra?: Record<string, string | number>): string {
  return "r|" + tipo + "|" + da + "|" + a + "|" + confronti + "|" + (extra ? JSON.stringify(extra) : "{}");
}

export function DataProvider({ da, a, confronti, children }: {
  da: string; a: string; confronti: number; children: React.ReactNode;
}) {
  const [map, setMap] = useState<Record<string, Entry>>({});
  const done = useRef<Set<string>>(new Set());
  const inflight = useRef<Set<string>>(new Set());

  const ensure = (key: string, fetcher: () => Promise<unknown>) => {
    if (done.current.has(key) || inflight.current.has(key)) return;
    inflight.current.add(key);
    setMap((m) => ({ ...m, [key]: { s: "loading" } }));
    fetcher()
      .then((data) => {
        done.current.add(key);
        setMap((m) => ({ ...m, [key]: { s: "ok", data } }));
      })
      .catch((e) => {
        setMap((m) => ({ ...m, [key]: { s: "err", msg: String((e as Error)?.message ?? e),
                                        unauth: e instanceof UnauthorizedError } }));
      })
      .finally(() => { inflight.current.delete(key); });
  };

  /* caricamento unico: tutto il menu del periodo, in parallelo */
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
    <DataCtx.Provider value={{ map, ensure }}>
      {children}
    </DataCtx.Provider>
  );
}

export interface Cached<T> {
  data?: T;
  loading: boolean;
  authErr: boolean;
  error: string | null;
}

function pick<T>(e: Entry | undefined): Cached<T> {
  if (!e) return { loading: true, authErr: false, error: null };
  if (e.s === "ok") return { data: e.data as T, loading: false, authErr: false, error: null };
  if (e.s === "err") return { loading: false, authErr: e.unauth, error: e.msg };
  return { loading: true, authErr: false, error: null };
}

export function useReport(tipo: string, da: string, a: string, confronti: number,
                          extra?: Record<string, string | number>): Cached<ReportResp> {
  const { map, ensure } = useContext(DataCtx);
  const key = keyReport(tipo, da, a, confronti, extra);
  useEffect(() => {
    ensure(key, () => getReport(tipo, da, a, confronti, extra));
  }, [key]);
  return pick<ReportResp>(map[key]);
}

export function useVendite(da: string, a: string, group: string): Cached<VenditeResp> {
  const { map, ensure } = useContext(DataCtx);
  const key = "v|" + group + "|" + da + "|" + a;
  useEffect(() => {
    ensure(key, () => getVenditeGroup(da, a, group));
  }, [key]);
  return pick<VenditeResp>(map[key]);
}
