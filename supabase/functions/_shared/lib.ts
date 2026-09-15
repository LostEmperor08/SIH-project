// =====================================================================
// _shared/lib.ts — common helpers for all SKV edge functions
// =====================================================================
import { createClient, SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

export const CORS = {
  "Access-Control-Allow-Origin": Deno.env.get("ALLOWED_ORIGIN") ?? "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
};

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

/** Service-role client — bypasses RLS. Only ever used server-side. */
export function admin(): SupabaseClient {
  return createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );
}

/** Caller-scoped client — keeps the user's JWT so RLS applies. */
export function asUser(req: Request): SupabaseClient {
  return createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_ANON_KEY")!,
    {
      global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } },
      auth: { persistSession: false },
    },
  );
}

/** Reject anyone below the required role. Returns the user or throws. */
export async function requireRole(req: Request, min: "viewer" | "analyst" | "investigator" | "admin") {
  const sb = asUser(req);
  const { data: { user } } = await sb.auth.getUser();
  if (!user) throw new HttpError(401, "authentication required");
  const { data, error } = await sb.rpc("has_min_role", { required: min });
  if (error || !data) throw new HttpError(403, `role '${min}' required`);
  return { user, sb };
}

export class HttpError extends Error {
  constructor(public status: number, msg: string) { super(msg); }
}

/** Fetch with timeout, retry and exponential backoff — public APIs rate-limit. */
export async function safeFetch(url: string, opts: RequestInit = {}, retries = 3): Promise<Response> {
  for (let i = 0; i <= retries; i++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 15_000);
    try {
      const res = await fetch(url, { ...opts, signal: ctl.signal });
      clearTimeout(timer);
      if (res.status === 429 || res.status >= 500) throw new Error(`upstream ${res.status}`);
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      return res;
    } catch (e) {
      clearTimeout(timer);
      if (i === retries) throw e;
      await new Promise((r) => setTimeout(r, 400 * 2 ** i + Math.random() * 300));
    }
  }
  throw new Error("unreachable");
}

/** Live USD price with a 60s in-memory cache (keeps you inside free tiers). */
const priceCache = new Map<string, { v: number; t: number }>();
export async function usdPrice(id: "bitcoin" | "ethereum"): Promise<number> {
  const hit = priceCache.get(id);
  if (hit && Date.now() - hit.t < 60_000) return hit.v;
  try {
    const r = await safeFetch(`https://api.coingecko.com/api/v3/simple/price?ids=${id}&vs_currencies=usd`);
    const j = await r.json();
    const v = j[id].usd as number;
    priceCache.set(id, { v, t: Date.now() });
    return v;
  } catch {
    return hit?.v ?? (id === "bitcoin" ? 0 : 0);
  }
}

export const sha256 = async (s: string) => {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
};

export const chunk = <T>(a: T[], n: number): T[][] =>
  Array.from({ length: Math.ceil(a.length / n) }, (_, i) => a.slice(i * n, i * n + n));
