import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { getConfig } from "./api";

/* Client Supabase per il login email+password con 2FA TOTP (MFA nativo di
   Supabase Auth). Le credenziali del progetto arrivano da /api/v1/config,
   quindi niente segreti nella build. */

let client: SupabaseClient | null = null;
let clientPromise: Promise<SupabaseClient> | null = null;

export async function ensureClient(): Promise<SupabaseClient> {
  if (client) return client;
  if (!clientPromise) {
    clientPromise = getConfig().then((cfg) => {
      client = createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
      return client;
    });
  }
  return clientPromise;
}

/* Login email+password. Se l'utente ha un fattore TOTP verificato la sessione
   resta incompleta finche' non si verifica il codice a 6 cifre. */
export async function signIn(email: string, password: string): Promise<string[]> {
  const c = await ensureClient();
  const { error } = await c.auth.signInWithPassword({ email, password });
  if (error) throw error;
  const { data } = await c.auth.mfa.listFactors();
  return (data?.all ?? [])
    .filter((f) => f.factor_type === "totp" && f.status === "verified")
    .map((f) => f.id);
}

export async function challenge(factorId: string): Promise<string> {
  const c = await ensureClient();
  const { data, error } = await c.auth.mfa.challenge({ factorId });
  if (error) throw error;
  return data.id;
}

export async function verifyTotp(factorId: string, challengeId: string, code: string): Promise<void> {
  const c = await ensureClient();
  const { error } = await c.auth.mfa.verify({ factorId, challengeId, code });
  if (error) throw error;
}

export async function listVerifiedTotp(): Promise<string[]> {
  const c = await ensureClient();
  const { data } = await c.auth.mfa.listFactors();
  return (data?.all ?? [])
    .filter((f) => f.factor_type === "totp" && f.status === "verified")
    .map((f) => f.id);
}

/* Elenco di TUTTI i fattori totp (verified e new/unverified). */
export async function listAllTotp(): Promise<{ id: string; status: string }[]> {
  const c = await ensureClient();
  const { data } = await c.auth.mfa.listFactors();
  return (data?.all ?? [])
    .filter((f) => f.factor_type === "totp")
    .map((f) => ({ id: f.id, status: f.status }));
}

/* Rimozione di un fattore (per pulire i fattori "new" mai confermati:
   Supabase rifiuta enroll oltre il limite di fattori per utente). */
export async function unenrollFactor(factorId: string): Promise<void> {
  const c = await ensureClient();
  const { error } = await c.auth.mfa.unenroll({ factorId });
  if (error) throw error;
}

/* Cancella tutti i fattori totp non verificati, poi enroll. Cosi' i tentativi
   abbandonati non si accumulano sull'account. */
export async function enrollTotpClean(): Promise<{ id: string; secret: string; uri: string }> {
  const all = await listAllTotp();
  const stale = all.filter((f) => f.status !== "verified");
  for (const f of stale) {
    try { await unenrollFactor(f.id); } catch { /* prosegue comunque */ }
  }
  return enrollTotp();
}

/* Attivazione 2FA: crea il fattore TOTP e restituisce segreto + URI otpauth
   da inserire a mano nell'app authenticator (o da mostrare come QR). */
export async function enrollTotp(): Promise<{ id: string; secret: string; uri: string }> {
  const c = await ensureClient();
  const { data, error } = await c.auth.mfa.enroll({ factorType: "totp" });
  if (error) throw error;
  return { id: data.id, secret: data.totp.secret, uri: data.totp.qr_code };
}

/* Conferma dell'attivazione: verifica il primo codice generato dall'app. */
export async function confirmEnroll(factorId: string, code: string): Promise<void> {
  const challengeId = await challenge(factorId);
  await verifyTotp(factorId, challengeId, code);
}

export async function currentSession(): Promise<{ email: string | null } | null> {
  const c = await ensureClient();
  const { data } = await c.auth.getSession();
  if (!data.session) return null;
  return { email: ((data.session.user?.email as string) ?? null) };
}

/* Tiene sincronizzato il token per le chiamate API (login, refresh, logout). */
export async function watchSession(cb: (token: string | null) => void): Promise<() => void> {
  const c = await ensureClient();
  const { data } = await c.auth.getSession();
  cb(data.session?.access_token ?? null);
  const { data: sub } = c.auth.onAuthStateChange((_evt, s) => cb(s?.access_token ?? null));
  return () => sub.subscription.unsubscribe();
}

export async function signOut(): Promise<void> {
  const c = await ensureClient();
  await c.auth.signOut();
}
