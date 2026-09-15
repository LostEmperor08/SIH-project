import { supabase, isSupabaseConfigured } from "./supabase.js";
import { readPref, writePref } from "./storage.js";

/**
 * Authentication is fail-closed: Supabase must be configured and the profiles
 * table must be reachable before an officer can sign in.
 */
let backendProbe = null;

export function authBackend() {
  if (backendProbe) return backendProbe;
  backendProbe = (async () => {
    if (!isSupabaseConfigured) return "unavailable";
    try {
      const { error } = await supabase.from("profiles").select("id").limit(1);
      // PGRST205 / 42P01 both mean "that table isn't there yet".
      if (error && (error.code === "PGRST205" || error.code === "42P01" || /schema cache|does not exist/i.test(error.message ?? ""))) {
        return "unavailable";
      }
      if (error) return "unavailable";
      return "live";
    } catch {
      return "unavailable";
    }
  })();
  return backendProbe;
}

async function isLive() {
  const backend = await authBackend();
  return backend === "live";
}

const SESSION_KEY = "chakravyuh_officer_session";
const USERS_KEY = "chakravyuh_mock_users";
const AUDIT_KEY = "chakravyuh_mock_audit";
const DOSSIER_REVIEW_KEY = "chakravyuh_mock_reviews";

const SEED_USERS = [
  {
    id: "u-user01",
    email: "user01@gmail.com",
    password: "Test@123",
    full_name: "Officer User01",
    badge_id: "I4C-IND-001",
    station_code: "CYBER-PS-I4C-DELHI",
    clearance: "Tier 1 - Unit Attribution",
    role: "admin",
    status: "active",
    created_at: "2026-09-15T12:00:00Z",
  },
  {
    id: "u-admin",
    email: "admin@chakravyuh.in",
    password: "admin123",
    full_name: "Inspector A. Sharma",
    badge_id: "I4C-IND-88219",
    station_code: "CYBER-PS-I4C-DELHI",
    clearance: "Tier 3 - Cross-Border / FIU",
    role: "admin",
    status: "active",
    created_at: "2026-06-02T09:15:00Z",
  },
  {
    id: "u-io-1",
    email: "r.iyer@police.gov.in",
    password: "demo1234",
    full_name: "SI R. Iyer",
    badge_id: "MH-CYB-4417",
    station_code: "CID-CYBER-MUMBAI",
    clearance: "Tier 2 - National Attribution",
    role: "investigator",
    status: "active",
    created_at: "2026-07-19T06:40:00Z",
  },
  {
    id: "u-io-2",
    email: "k.menon@police.gov.in",
    password: "demo1234",
    full_name: "ASI K. Menon",
    badge_id: "KA-STF-2290",
    station_code: "STF-CYBER-BENGALURU",
    clearance: "Tier 1 - Unit Attribution",
    role: "investigator",
    status: "pending",
    created_at: "2026-08-30T11:05:00Z",
  },
  {
    id: "u-view-1",
    email: "audit.cell@fiuind.gov.in",
    password: "demo1234",
    full_name: "FIU Audit Cell",
    badge_id: "FIU-OBS-0031",
    station_code: "FIU-IND-NODAL-CELL",
    clearance: "Tier 1 - Unit Attribution",
    role: "viewer",
    status: "active",
    created_at: "2026-09-01T14:22:00Z",
  },
];

const SEED_AUDIT = [
  { id: 3, actor_email: "admin@chakravyuh.in", action: "dossier.approved", target: "SIH/2026/00412", created_at: "2026-09-12T10:12:00Z" },
  { id: 2, actor_email: "r.iyer@police.gov.in", action: "account.signin", target: "r.iyer@police.gov.in", created_at: "2026-09-12T09:41:00Z" },
  { id: 1, actor_email: "admin@chakravyuh.in", action: "user.role_changed", target: "k.menon@police.gov.in", detail: { role: "investigator" }, created_at: "2026-09-11T16:03:00Z" },
];

/** Credentials shown on the sign-in screen so the demo is self-explanatory. */
export const DEMO_CREDENTIALS = [
  { label: "Officer User01", email: "user01@gmail.com", password: "Test@123" },
  { label: "Administrator", email: "admin@chakravyuh.in", password: "admin123" },
  { label: "Investigator", email: "r.iyer@police.gov.in", password: "demo1234" },
];

function read(key, fallback) {
  try {
    const raw = readPref(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    writePref(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
}

function users() {
  return read(USERS_KEY, SEED_USERS);
}

function saveUsers(list) {
  write(USERS_KEY, list);
}

function strip(user) {
  if (!user) return null;
  const rest = { ...user };
  delete rest.password;
  return rest;
}

// ── Authentication ──────────────────────────────────────────────────────
export async function signUpOfficer({ email, password, fullName, badgeId, stationCode, clearance }) {
  if (await isLive()) {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { full_name: fullName, badge_id: badgeId, station_code: stationCode, clearance } },
    });
    if (error) throw error;
    await logAudit("account.signup", email, null);
    return data;
  }

  const list = users();
  const normalized = String(email).trim().toLowerCase();
  if (list.some((u) => u.email.toLowerCase() === normalized)) {
    throw new Error("An account with that email already exists. Sign in instead.");
  }
  const account = {
    id: `u-${Date.now()}`,
    email: normalized,
    password,
    full_name: fullName || normalized.split("@")[0],
    badge_id: badgeId || "—",
    station_code: stationCode || "—",
    clearance: clearance || "Tier 1 - Unit Attribution",
    role: "investigator",
    status: "active",
    created_at: new Date().toISOString(),
  };
  saveUsers([account, ...list]);
  write(SESSION_KEY, strip(account));
  await logAudit("account.signup", normalized, { badge_id: account.badge_id });
  return { session: { user: strip(account) } };
}

export async function signInOfficer({ email, password }) {
  if (await isLive()) {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    await logAudit("account.signin", email, null);
    return data;
  }

  const normalized = String(email).trim().toLowerCase();
  const match = users().find((u) => u.email.toLowerCase() === normalized);
  if (!match) throw new Error("No account found for that email. Use Request Access to create one.");
  if (match.password !== password) throw new Error("Incorrect password.");
  if (match.status === "suspended") throw new Error("This account is suspended. Contact an administrator.");
  write(SESSION_KEY, strip(match));
  await logAudit("account.signin", normalized, null);
  return { session: { user: strip(match) } };
}

export async function signOutOfficer() {
  await logAudit("account.signout", null, null);
  if (await isLive()) await supabase.auth.signOut();
  try {
    writePref(SESSION_KEY, "");
  } catch {
    /* storage unavailable */
  }
}

export async function getSessionUser() {
  if (await isLive()) {
    const { data } = await supabase.auth.getUser();
    return data?.user ?? null;
  }
  return read(SESSION_KEY, null);
}

export async function getMyProfile() {
  const session = await getSessionUser();
  if (!session) return null;
  if (await isLive()) {
    const { data, error } = await supabase.from("profiles").select("*").eq("id", session.id).maybeSingle();
    if (error) return { id: session.id, email: session.email, role: "investigator", status: "active" };
    return data ?? { id: session.id, email: session.email, role: "investigator", status: "active" };
  }
  // Re-read from the user store so role changes made in the admin panel show up.
  return users().map(strip).find((u) => u.id === session.id) ?? session;
}

export async function updateMyProfile(patch) {
  const session = await getSessionUser();
  if (!session) throw new Error("No active session.");
  if (await isLive()) {
    const { error } = await supabase.from("profiles").update(patch).eq("id", session.id);
    if (error) throw error;
  } else {
    saveUsers(users().map((u) => (u.id === session.id ? { ...u, ...patch } : u)));
    write(SESSION_KEY, { ...session, ...patch });
  }
  await logAudit("profile.updated", session.email, patch);
}

// ── Administration ──────────────────────────────────────────────────────
export async function listProfiles() {
  if (await isLive()) {
    const { data, error } = await supabase.from("profiles").select("*").order("created_at", { ascending: false });
    if (error) throw error;
    return data ?? [];
  }
  return users().map(strip);
}

export async function setProfileRole(id, role) {
  if (await isLive()) {
    const { error } = await supabase.from("profiles").update({ role }).eq("id", id);
    if (error) throw error;
  } else {
    saveUsers(users().map((u) => (u.id === id ? { ...u, role } : u)));
  }
  await logAudit("user.role_changed", id, { role });
}

export async function setProfileStatus(id, status) {
  if (await isLive()) {
    const { error } = await supabase.from("profiles").update({ status }).eq("id", id);
    if (error) throw error;
  } else {
    saveUsers(users().map((u) => (u.id === id ? { ...u, status } : u)));
  }
  await logAudit("user.status_changed", id, { status });
}

export async function listAuditLog(limit = 100) {
  if (await isLive()) {
    const { data, error } = await supabase
      .from("audit_log")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit);
    if (error) throw error;
    return data ?? [];
  }
  return read(AUDIT_KEY, SEED_AUDIT).slice(0, limit);
}

export async function logAudit(action, target, detail) {
  try {
    if (await isLive()) {
      const { error } = await supabase.rpc("append_audit", {
        p_action: action,
        p_target: target ?? null,
        p_detail: detail ?? null,
      });
      if (error) throw error;
      return;
    }
    const session = await getSessionUser();
    const entry = {
      id: Date.now(),
      actor_id: session?.id ?? null,
      actor_email: session?.email ?? (typeof target === "string" && target.includes("@") ? target : null),
      action,
      target: target ?? null,
      detail: detail ?? null,
      created_at: new Date().toISOString(),
    };
    write(AUDIT_KEY, [entry, ...read(AUDIT_KEY, SEED_AUDIT)].slice(0, 200));
  } catch (err) {
    console.warn("audit log skipped", err?.message ?? err);
  }
}

/** Review decisions layered over whatever dossier list the app already has. */
export function dossierReviews() {
  return read(DOSSIER_REVIEW_KEY, {});
}

export async function reviewDossier(id, approvalStatus, note) {
  if (await isLive()) {
    const { error } = await supabase.rpc("review_dossier", {
      p_dossier_id: id,
      p_approval_status: approvalStatus,
      p_note: note ?? null,
    });
    if (error) throw error;
  } else {
    write(DOSSIER_REVIEW_KEY, {
      ...dossierReviews(),
      [id]: { approval_status: approvalStatus, approved_at: new Date().toISOString(), review_note: note ?? null },
    });
  }
  await logAudit(`dossier.${approvalStatus}`, id, { note: note ?? null });
}
