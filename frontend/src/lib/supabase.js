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
    address: item.id || item.address || item.origin_sender || item.counterparty,
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
      const { data, error } = await supabase.from("dossiers").select("*").order("created_at", { ascending: false });
      if (!error && data) return data;
    } catch (err) {
      console.warn("Supabase dossiers fetch fallback", err);
    }
  }
  return notConfigured("dossiers");
}

export async function saveDossier(dossier) {
  const newDossier = {
    id: `d-${Date.now()}`,
    case_ref: dossier.case_ref || `SIH/2026/${Math.floor(1000 + Math.random() * 9000)}`,
    title: dossier.title || "Cryptographic Attribution Dossier",
    // NEVER default the VASP. Naming the wrong exchange sends the freeze
    // request to the wrong place and burns the only chance to recover funds.
    target_vasp: dossier.target_vasp || null,
    deposit_address: dossier.deposit_address || "0x...",
    total_traced_usdt: dossier.total_traced_usdt || 0,
    total_traced_inr: dossier.total_traced_inr || 0,
    confidence: dossier.confidence || "95%",
    status: "NOTICE_ISSUED",
    statutory_act: "BNSS Sec 94 / Indian Evidence Act Sec 65B",
    created_at: new Date().toISOString(),
    io_name: dossier.io_name || "Investigating Officer",
    ...dossier
  };

  const current = getLocal("dossiers", []);
  const updated = [newDossier, ...current];
  setLocal("dossiers", updated);

  if (isSupabaseConfigured) {
    try {
      await supabase.from("dossiers").insert([newDossier]);
    } catch (err) {
      console.warn("Supabase dossier insert error", err);
    }
  }

  return newDossier;
}

// ── Evidence Records Operations (Live DB & Local Cache) ────────────────
export async function fetchEvidenceRecords() {
  if (isSupabaseConfigured) {
    try {
      const { data, error } = await supabase.from("evidence_ledger").select("*").order("hop", { ascending: true });
      if (!error && data && data.length > 0) return data;
    } catch (err) {
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
