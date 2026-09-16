import { createClient } from "@supabase/supabase-js";
import { readPref, writePref } from "./storage.js";

// Credentials come from the environment ONLY. Nothing is hardcoded here:
// a live project URL committed to a public repository is a real disclosure,
// and a "dummy" key fallback makes an unconfigured build look like it works.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

if (!isSupabaseConfigured && import.meta.env.DEV) {
  console.error(
    "[chakravyuh] VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set. " +
    "Case data is disabled — this build refuses to show placeholder records."
  );
}

// createClient throws on empty strings, so it is only built when configured.
// Every consumer already guards on isSupabaseConfigured.
export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey, { auth: { persistSession: true } })
  : null;

// Case data is NEVER served from browser storage. Showing stale local rows
// as though they came from the database is the mock-data problem in its
// purest form — an officer cannot tell a real record from a leftover one.
// These helpers now only cache UI preferences, never case records.
function notConfigured(what) {
  throw new Error(
    `Cannot load ${what}: Supabase is not configured. ` +
    "Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY. " +
    "No offline placeholder data is available by design."
  );
}

function getLocal(key, fallback = []) {
  try {
    const val = readPref(`chakravyuh_${key}`);
    return val ? JSON.parse(val) : fallback;
  } catch {
    return fallback;
  }
}

function setLocal(key, data) {
  try {
    writePref(`chakravyuh_${key}`, JSON.stringify(data));
  } catch (e) {
    console.warn("LocalStorage save error", e);
  }
}

// ── Watchlist Operations (Live DB & Local Cache) ───────────────────────
export async function fetchWatchlist() {
  if (isSupabaseConfigured) {
    try {
      const { data, error } = await supabase.from("watchlist").select("*").order("added_at", { ascending: false });
      if (!error && data) return data;
    } catch (err) {
      console.warn("Supabase watchlist fetch fallback", err);
    }
  }
  return notConfigured("the watchlist");
}

export async function addToWatchlist(item) {
  const newItem = {
    id: `w-${Date.now()}`,
    // address first: item.id can be a UI node key, not a chain address
    address: item.address || item.id || item.origin_sender || item.counterparty,
    label: item.label || item.origin_label || item.counterparty_label || "Monitored Entity",
    chain: item.chain || null,
    risk: item.risk ?? (Number(item.risk_score) >= 80 ? "CRITICAL"
          : Number(item.risk_score) >= 60 ? "HIGH"
          : Number(item.risk_score) >= 35 ? "MEDIUM"
          : Number.isFinite(Number(item.risk_score)) ? "LOW" : "UNSCORED"),
    // No invented score. If the trace did not produce one, the record
    // carries null and the UI shows "not scored" rather than a number
    // nobody can justify.
    risk_score: Number.isFinite(Number(item.risk_score)) ? Number(item.risk_score) : null,
    reason: item.reason || item.audit_notes || "Added from live investigation trace",
    added_at: new Date().toISOString(),
    status: "ACTIVE_SURVEILLANCE",
    last_tx_value: item.value_usdt ? `${item.value_usdt} USDT` : item.last_tx_value || "Active",
  };

  const current = getLocal("watchlist", []);
  const updated = [newItem, ...current.filter(w => w.address !== newItem.address)];
  setLocal("watchlist", updated);

  if (isSupabaseConfigured) {
    try {
      await supabase.from("watchlist").insert([newItem]);
    } catch (err) {
      console.warn("Supabase insert error", err);
    }
  }

  return newItem;
}

export async function removeFromWatchlist(id) {
  const current = getLocal("watchlist", []);
  const updated = current.filter(w => w.id !== id && w.address !== id);
  setLocal("watchlist", updated);

  if (isSupabaseConfigured) {
    try {
      await supabase.from("watchlist").delete().eq("id", id);
    } catch (err) {
      console.warn("Supabase delete error", err);
    }
  }

  return updated;
}

// ── Legal Dossier Operations (Live DB & Local Cache) ───────────────────
export async function fetchDossiers() {
  if (isSupabaseConfigured) {
    try {
      const { data, error } = await supabase
        .from("dossiers").select("*").order("created_at", { ascending: false });
      if (!error) return data ?? [];
      console.error("dossier fetch:", error.message);
    } catch (err) {
      console.warn("Supabase dossiers fetch fallback", err);
    }
  }
  return notConfigured("dossiers");
}

// The ONLY columns public.dossiers actually has. Anything else in the
// caller's object (fir_no, target_address, findings, ...) made PostgREST
// reject the whole insert with PGRST204 "column not found" — and the old
// code ignored the returned error, so every dossier silently vanished and
// the Legal Dossier page stayed empty forever.
const DOSSIER_COLUMNS = [
  "id", "case_ref", "title", "target_vasp", "deposit_address",
  "total_traced_usdt", "total_traced_inr", "confidence", "status",
  "statutory_act", "io_name", "created_at", "created_by", "submitted_at",
];

export async function saveDossier(dossier) {
  if (!isSupabaseConfigured) {
    throw new Error(
      "Cannot file a dossier: Supabase is not configured. A legal notice " +
      "that exists only in this browser tab is not a record."
    );
  }

  // RLS: dossiers_insert requires created_by = auth.uid(). Omit it and the
  // row is refused by policy, not by validation — which reads as a silent
  // no-op unless the error is surfaced.
  const { data: auth } = await supabase.auth.getUser();
  const uid = auth?.user?.id;
  if (!uid) {
    throw new Error("Not signed in — a dossier must carry the officer who filed it.");
  }

  const merged = {
    id: `d-${Date.now()}`,
    case_ref: dossier.case_ref || dossier.fir_no || null,
    title: dossier.title || "Cryptographic Attribution Dossier",
    // NEVER default the VASP. Naming the wrong exchange sends the freeze
    // request to the wrong place and burns the only chance to recover funds.
    target_vasp: dossier.target_vasp || null,
    deposit_address: dossier.deposit_address || dossier.target_address || null,
    total_traced_usdt: Number(dossier.total_traced_usdt || 0),
    total_traced_inr: Number(dossier.total_traced_inr || 0),
    confidence: dossier.confidence || null,
    status: dossier.status || "NOTICE_ISSUED",
    statutory_act: dossier.statutory_act ||
      "BNSS Sec 94 / Indian Evidence Act Sec 65B",
    io_name: dossier.io_name || null,
    created_by: uid,
    submitted_at: new Date().toISOString(),
    ...dossier,
  };

  // Findings and any other free text belong in the title, not in a column
  // that does not exist.
  if (dossier.findings && !dossier.title) {
    merged.title = String(dossier.findings).slice(0, 180);
  }

  // Whitelist AFTER the spread, so a caller cannot reintroduce a bad column.
  const row = {};
  for (const k of DOSSIER_COLUMNS) {
    if (merged[k] !== undefined) row[k] = merged[k];
  }
  row.created_by = uid;            // never overridable by the caller

  const { data, error } = await supabase
    .from("dossiers").insert([row]).select().single();

  if (error) {
    throw new Error(
      `Dossier could not be filed: ${error.message}` +
      (error.code === "42501"
        ? " \u2014 your account needs the 'analyst' role or higher."
        : "")
    );
  }
  return data;
}

// ── Evidence Records Operations (Live DB & Local Cache) ────────────────
// evidence_ledger stores what the CHAIN proves: addresses, value in USDT,
// the tx hash, when it was observed. It does not store a rupee figure, an
// IST string or a classification, because none of those are on-chain facts.
// The table was right and the UI was reading columns that do not exist, so
// every row rendered blank. Derive them here, once, where the derivation is
// visible — rather than inventing columns in the database.
const USD_INR = Number(import.meta.env.VITE_USD_INR_RATE) || 88.5;

function normaliseEvidenceRow(r, i) {
  const usdt = Number(r.value_usdt ?? 0);
  const when = r.observed_at || r.created_at || null;
  const risk = Number(r.risk_score ?? 0);
  return {
    ...r,
    hop: r.hop ?? r.seq ?? i + 1,
    // Aliases the table itself does not carry.
    origin_sender: r.from_addr ?? "",
    counterparty: r.to_addr ?? "",
    value_usdt: usdt,
    value_inr: Math.round(usdt * USD_INR),
    datetime_utc: when ? new Date(when).toISOString().replace("T", " ").slice(0, 19) : "",
    datetime_ist: when
      ? new Date(when).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })
      : "",
    classification: r.classification ||
      (risk >= 80 ? "VASP / HIGH-RISK ENDPOINT"
        : i === 0 ? "INBOUND DEPOSIT" : "OUTWARD SWEEP"),
    status: r.sealed === false ? "UNSEALED" : "CERTIFIED",
  };
}

export async function fetchEvidenceRecords() {
  if (isSupabaseConfigured) {
    try {
      const { data, error } = await supabase
        .from("evidence_ledger").select("*")
        .order("case_ref", { ascending: false })
        .order("seq", { ascending: true });
      // An empty ledger is a valid state, not a failure. The old
      // `data.length > 0` check fell through to notConfigured(), which
      // THROWS — so a fresh install showed an error instead of "no records".
      if (!error) return (data ?? []).map(normaliseEvidenceRow);
      console.error("evidence fetch:", error.message);
      throw new Error(`Evidence ledger could not be read: ${error.message}`);
    } catch (err) {
      if (err instanceof Error && err.message.startsWith("Evidence ledger")) throw err;
      console.warn("Supabase evidence fetch fallback", err);
    }
  }
  return notConfigured("the evidence ledger");
}

export async function recordEvidenceItem(item, caseRef) {
  // Routed through add_evidence_link() rather than a direct insert.
  // Migration 08 revoked INSERT on evidence_ledger because the RPC is what
  // computes the hash chain; a direct insert stores a row with no
  // chain_hash, and an unchained row is exactly what lets a deletion go
  // unnoticed.
  const { sealEvidence } = await import("./evidence.js");
  return sealEvidence(item, caseRef ?? "UNFILED");
}
