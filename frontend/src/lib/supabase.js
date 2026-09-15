import { createClient } from "@supabase/supabase-js";
import { EVIDENCE_RECORDS } from "./evidenceData.js";
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

// ── Initial Mock / Cache Seed Data ──────────────────────────────────────
const DEFAULT_WATCHLIST = [
  {
    id: "w-1",
    address: "0xe6d634289cf30114041b63e6358",
    label: "Primary Layering Mule (Case #41029)",
    chain: "Polygon PoS",
    risk: "CRITICAL",
    risk_score: 96,
    reason: "Rapid peel dispersion post victim credit",
    added_at: "2026-09-10T11:20:00Z",
    status: "ACTIVE_SURVEILLANCE",
    last_tx_value: "30.18 USDT",
  },
  {
    id: "w-2",
    address: "TX7sK...victim",
    label: "Reported Scammer Inbound Node",
    chain: "Tron (TRC-20)",
    risk: "CRITICAL",
    risk_score: 95,
    reason: "NCRP victim reporting stream match",
    added_at: "2026-09-08T14:45:00Z",
    status: "ACTIVE_SURVEILLANCE",
    last_tx_value: "50,000.00 USDT",
  },
  {
    id: "w-3",
    address: "0xbf5e8a1042df5e08b1a2928",
    label: "Consolidation Wallet (Pre-VASP)",
    chain: "Polygon PoS",
    risk: "HIGH",
    risk_score: 89,
    reason: "Batch sweeper into exchange hot wallet",
    added_at: "2026-09-05T09:12:00Z",
    status: "STANDBY",
    last_tx_value: "220.00 USDT",
  },
];

const DEFAULT_DOSSIERS = [
  {
    id: "d-1",
    case_ref: "SIH/2026/00412",
    title: "Telegram Task Scam — Layering to Binance",
    target_vasp: "Binance",
    deposit_address: "TR4xp...deposit",
    total_traced_usdt: 49204,
    total_traced_inr: 4379156,
    confidence: "95%",
    status: "NOTICE_ISSUED",
    statutory_act: "BNSS Sec 94 / CrPC Sec 91",
    created_at: "2026-09-04T12:00:00Z",
    io_name: "Inspector A. Sharma",
  },
  {
    id: "d-2",
    case_ref: "I4C/2026/09921",
    title: "Part-time Job Crypto Laundering Ring",
    target_vasp: "WazirX / CoinDCX Cluster",
    deposit_address: "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be",
    total_traced_usdt: 12500,
    total_traced_inr: 1112500,
    confidence: "92%",
    status: "FREEZE_DIRECTIVE_ACTIVE",
    statutory_act: "BNSS Sec 94",
    created_at: "2026-08-28T16:30:00Z",
    io_name: "Inspector A. Sharma",
  },
];

// Helper to get from LocalStorage or seed default
function getLocal(key, fallback) {
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

// ── Watchlist Operations ──────────────────────────────────────────────
export async function fetchWatchlist() {
  if (isSupabaseConfigured) {
    try {
      const { data, error } = await supabase.from("watchlist").select("*").order("added_at", { ascending: false });
      if (!error && data && data.length > 0) return data;
    } catch (err) {
      console.warn("Supabase watchlist fetch fallback to cache", err);
    }
  }
  return getLocal("watchlist", DEFAULT_WATCHLIST);
}

export async function addToWatchlist(item) {
  const newItem = {
    id: `w-${Date.now()}`,
    address: item.id || item.address || item.origin_sender || item.counterparty,
    label: item.label || item.origin_label || item.counterparty_label || "Monitored Entity",
    chain: item.chain || "Polygon PoS",
    risk: item.risk_score >= 90 ? "CRITICAL" : "HIGH",
    risk_score: item.risk_score || 92,
    reason: item.reason || item.audit_notes || "Added from live investigation trace",
    added_at: new Date().toISOString(),
    status: "ACTIVE_SURVEILLANCE",
    last_tx_value: item.value_usdt ? `${item.value_usdt} USDT` : "Active",
  };

  const current = getLocal("watchlist", DEFAULT_WATCHLIST);
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
  const current = getLocal("watchlist", DEFAULT_WATCHLIST);
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

// ── Legal Dossier Operations ──────────────────────────────────────────
export async function fetchDossiers() {
  if (isSupabaseConfigured) {
    try {
      const { data, error } = await supabase.from("dossiers").select("*").order("created_at", { ascending: false });
      if (!error && data && data.length > 0) return data;
    } catch (err) {
      console.warn("Supabase dossiers fetch fallback", err);
    }
  }
  return getLocal("dossiers", DEFAULT_DOSSIERS);
}

export async function saveDossier(dossier) {
  const newDossier = {
    id: `d-${Date.now()}`,
    case_ref: dossier.case_ref || `SIH/2026/${Math.floor(1000 + Math.random() * 9000)}`,
    title: dossier.title || "Cryptographic Attribution Dossier",
    target_vasp: dossier.target_vasp || "Binance",
    deposit_address: dossier.deposit_address || "0x...",
    total_traced_usdt: dossier.total_traced_usdt || 20.08,
    total_traced_inr: dossier.total_traced_inr || 1787,
    confidence: dossier.confidence || "95%",
    status: "NOTICE_ISSUED",
    statutory_act: "BNSS Sec 94 / Indian Evidence Act Sec 65B",
    created_at: new Date().toISOString(),
    io_name: "Inspector A. Sharma",
    ...dossier
  };

  const current = getLocal("dossiers", DEFAULT_DOSSIERS);
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

// ── Evidence Records Operations ────────────────────────────────────────
export async function fetchEvidenceRecords() {
  if (isSupabaseConfigured) {
    try {
      const { data, error } = await supabase.from("evidence_ledger").select("*").order("hop", { ascending: true });
      if (!error && data && data.length > 0) return data;
    } catch (err) {
      console.warn("Supabase evidence fetch fallback", err);
    }
  }
  return getLocal("evidence_records", EVIDENCE_RECORDS);
}
