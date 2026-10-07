import React, { createContext, useContext, useEffect, useState } from "react";
import { getApiKey, setApiKey, clearApiKey, onAuthChange, getMe, UnauthorizedError } from "./api";

/* Autenticazione con le chiavi API esistenti (tabella api_keys su Supabase,
   valori ecm_...): login = verifica della chiave contro /api/v1/me.
   La sessione e' persistente (localStorage "ea_api_key"), il logout la pulisce.
   Nessun nuovo backend: si riusa il gate X-API-Key della FastAPI. */

export interface MeInfo {
  via: string;
  nome: string;
}

interface AuthCtx {
  ready: boolean;            /* verifica iniziale della chiave salvata */
  authed: boolean;
  key: string;
  me: MeInfo | null;
  login: (k: string) => Promise<MeInfo>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>({
  ready: false, authed: false, key: "", me: null,
  login: async () => { throw new Error("no provider"); },
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [key, setKey] = useState(getApiKey());
  const [me, setMe] = useState<MeInfo | null>(null);
  const [authed, setAuthed] = useState(false);

  /* sincronizza su login/logout (anche da un'altra tab) */
  useEffect(() => {
    return onAuthChange(() => setKey(getApiKey()));
  }, []);

  /* verifica la chiave appena cambia (e all'avvio) */
  useEffect(() => {
    let alive = true;
    if (!key) {
      setMe(null);
      setAuthed(false);
      setReady(true);
      return;
    }
    setReady(false);
    getMe()
      .then((r) => {
        if (!alive) return;
        setMe({ via: r.via, nome: r.nome });
        setAuthed(true);
        setReady(true);
      })
      .catch((e) => {
        if (!alive) return;
        /* chiave salvata non piu valida: la si butta, si torna al login */
        if (e instanceof UnauthorizedError) clearApiKey();
        setMe(null);
        setAuthed(false);
        setReady(true);
      });
    return () => { alive = false; };
  }, [key]);

  const login = async (k: string): Promise<MeInfo> => {
    const prev = getApiKey();
    setApiKey(k); /* la usa anche la verifica: apiGet legge localStorage */
    try {
      const r = await getMe();
      const info = { via: r.via, nome: r.nome };
      setMe(info);
      setAuthed(true);
      return info;
    } catch (e) {
      setApiKey(prev); /* ripristina la chiave precedente se il login fallisce */
      throw e;
    }
  };

  const logout = () => {
    clearApiKey();
    setMe(null);
    setAuthed(false);
  };

  return (
    <Ctx.Provider value={{ ready, authed, key, me, login, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthCtx {
  return useContext(Ctx);
}