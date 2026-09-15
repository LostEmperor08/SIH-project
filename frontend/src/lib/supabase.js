import { createClient } from "@supabase/supabase-js";
import { readPref, writePref } from "./storage.js";

// Default Supabase project credentials or environment fallback
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || "https://kxyjtwvyzmxhyefgqbco.supabase.co";
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.dummy-key-for-local-fallback";

export const isSupabaseConfigured = Boolean(
  import.meta.env.VITE_SUPABASE_URL && 
  import.meta.env.VITE_SUPABASE_ANON_KEY &&
  !import.meta.env.VITE_SUPABASE_ANON_KEY.includes("dummy")
);

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: { persistSession: true },
});

// Helper to get from LocalStorage or empty list
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
  return getLocal("watchlist", []);
}

export async function addToWatchlist(item) {
  const newItem = {
    id: `w-${Date.now()}`,
    address: item.id || item.address || item.origin_sender || item.counterparty,
    label: item.label || item.origin_label || item.counterparty_label || "Monitored Entity",
    chain: item.chain || "Polygon PoS",
    risk: (item.risk_score >= 90 || item.risk === "CRITICAL") ? "CRITICAL" : "HIGH",
    risk_score: item.risk_score || 92,
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
  return getLocal("dossiers", []);
}

export async function saveDossier(dossier) {
  const newDossier = {
    id: `d-${Date.now()}`,
    case_ref: dossier.case_ref || `SIH/2026/${Math.floor(1000 + Math.random() * 9000)}`,
    title: dossier.title || "Cryptographic Attribution Dossier",
    target_vasp: dossier.target_vasp || "Binance",
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
  return getLocal("evidence_records", []);
}

export async function recordEvidenceItem(item) {
  const record = {
    id: item.id || `ev-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    hop: item.hop || 1,
    chain: item.chain || "Polygon PoS",
    tx_hash: item.tx_hash || "",
    from_addr: item.origin_sender || item.from_addr || "",
    to_addr: item.counterparty || item.to_addr || "",
    value_usdt: item.value_usdt || item.amount || 0,
    value_inr: item.value_inr || Math.round((item.value_usdt || item.amount || 0) * 89),
    classification: item.classification || "INVESTIGATION_RECORD",
    datetime_ist: item.datetime_ist || new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }),
    datetime_utc: item.datetime_utc || new Date().toISOString(),
    status: "CERTIFIED_SEC_65B",
  };

  const current = getLocal("evidence_records", []);
  const updated = [record, ...current.filter(r => r.tx_hash !== record.tx_hash)];
  setLocal("evidence_records", updated);

  if (isSupabaseConfigured) {
    try {
      await supabase.from("evidence_ledger").insert([record]);
    } catch (err) {
      console.warn("Supabase evidence insert error", err);
    }
  }

  return record;
}
