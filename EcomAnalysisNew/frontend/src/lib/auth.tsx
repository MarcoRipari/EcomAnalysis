import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { getApiKey, setApiKey, clearApiKey, onAuthChange, getMe, setApiToken, UnauthorizedError } from "./api";
import * as sb from "./supabase";

/* Autenticazione con DUE modalita':
   - "key": chiave API ecm_... verificata contro /api/v1/me (come prima);
   - "sb":  email + password su Supabase Auth con 2FA TOTP obbligatorio per
            gli utenti che hanno un fattore verificato (MFA nativo Supabase).
   La modalita' usata resta in localStorage ("ea_auth_mode"), il token utente
   viene tenuto in memoria (mai nel localStorage). */

export interface MeInfo {
  via: string;
  nome: string;
}

export type AuthMode = "key" | "sb";

interface AuthCtx {
  ready: boolean;
  authed: boolean;
  mode: AuthMode | null;
  key: string;
  me: MeInfo | null;
  email: string | null;
  loginWithKey: (k: string) => Promise<MeInfo>;
  loginStartEmail: (email: string, password: string) => Promise<{ needsCode: boolean; factorId?: string; challengeId?: string }>;
  loginVerifyCode: (factorId: string, challengeId: string, code: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>({
  ready: false, authed: false, mode: null, key: "", me: null, email: null,
  loginWithKey: async () => { throw new Error("no provider"); },
  loginStartEmail: async () => { throw new Error("no provider"); },
  loginVerifyCode: async () => { throw new Error("no provider"); },
  logout: () => {},
});

const MODE_STORAGE = "ea_auth_mode";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [mode, setModeS] = useState<AuthMode | null>(null);
  const [key, setKey] = useState(getApiKey());
  const [me, setMe] = useState<MeInfo | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const unwatch = useRef<(() => void) | null>(null);

  useEffect(() => {
    return onAuthChange(() => setKey(getApiKey()));
  }, []);

  /* verifica della chiave salvata (solo modalita' key) */
  useEffect(() => {
    if (mode !== "key") return;
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
        if (e instanceof UnauthorizedError) clearApiKey();
        setMe(null);
        setAuthed(false);
        setReady(true);
      });
    return () => { alive = false; };
  }, [key, mode]);

  /* avvio: riprende la sessione salvata (Supabase o chiave) */
  useEffect(() => {
    let alive = true;
    const m = localStorage.getItem(MODE_STORAGE);
    (async () => {
      if (m === "sb") {
        try {
          unwatch.current = await sb.watchSession((tk) => setApiToken(tk));
          const sess = await sb.currentSession();
          if (sess) {
            setEmail(sess.email);
            const r = await getMe();
            setMe({ via: r.via, nome: r.nome });
            setModeS("sb");
            setAuthed(true);
          } else {
            localStorage.removeItem(MODE_STORAGE);
          }
        } catch {
          localStorage.removeItem(MODE_STORAGE);
        }
        if (alive) setReady(true);
      } else if (m === "key" || getApiKey()) {
        setModeS("key");
        /* ready la decide l'effect della chiave */
      } else {
        if (alive) setReady(true);
      }
    })();
    return () => { alive = false; };
  }, []);

  const adoptSb = async (): Promise<void> => {
    if (!unwatch.current) unwatch.current = await sb.watchSession((tk) => setApiToken(tk));
    const sess = await sb.currentSession();
    if (!sess) throw new Error("Sessione non attiva.");
    localStorage.setItem(MODE_STORAGE, "sb");
    setEmail(sess.email);
    const r = await getMe();
    setMe({ via: r.via, nome: r.nome });
    setModeS("sb");
    setAuthed(true);
  };

  const loginWithKey = async (k: string): Promise<MeInfo> => {
    const prev = getApiKey();
    setApiKey(k);
    try {
      const r = await getMe();
      const info = { via: r.via, nome: r.nome };
      localStorage.setItem(MODE_STORAGE, "key");
      setModeS("key");
      setMe(info);
      setAuthed(true);
      return info;
    } catch (e) {
      setApiKey(prev);
      throw e;
    }
  };

  const loginStartEmail = async (em: string, pw: string) => {
    const factors = await sb.signIn(em, pw);
    if (factors.length) {
      const factorId = factors[0];
      const challengeId = await sb.challenge(factorId);
      return { needsCode: true, factorId, challengeId };
    }
    await adoptSb();
    return { needsCode: false };
  };

  const loginVerifyCode = async (factorId: string, challengeId: string, code: string) => {
    await sb.verifyTotp(factorId, challengeId, code);
    await adoptSb();
  };

  const logout = () => {
    if (mode === "sb") {
      setApiToken(null);
      sb.signOut().catch(() => {});
    }
    clearApiKey();
    localStorage.removeItem(MODE_STORAGE);
    setMe(null);
    setEmail(null);
    setAuthed(false);
    setModeS(null);
  };

  return (
    <Ctx.Provider value={{ ready, authed, mode, key, me, email, loginWithKey, loginStartEmail, loginVerifyCode, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthCtx {
  return useContext(Ctx);
}
