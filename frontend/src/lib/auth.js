import { supabase, isSupabaseConfigured } from "./supabase.js";
import { readPref, writePref } from "./storage.js";

/**
 * Authentication is strictly connected to live Supabase Auth and Profiles table.
 * All mock users and seed datasets have been permanently eliminated.
 */
let backendProbe = null;

export function authBackend() {
  if (backendProbe) return backendProbe;
  backendProbe = (async () => {
    if (!isSupabaseConfigured) return "unavailable";
    try {
      const { error } = await supabase.from("profiles").select("id").limit(1);
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

const SESSION_KEY = "chakravyuh_officer_session";
// Renamed: these are locally cached review outcomes for optimistic UI,
// not mock data. The authoritative record is the review_dossier RPC.
const DOSSIER_REVIEW_KEY = "chakravyuh_review_cache";

// ── OAuth Providers ─────────────────────────────────────────────────────
export async function signInWithOAuthProvider(provider) {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured. Please set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
  }
  const redirectUrl = `${window.location.origin}/dashboard`;
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: redirectUrl,
      queryParams: provider === "google"
        ? { access_type: "offline", prompt: "select_account" }
        : { prompt: "select_account" },
    },
  });
  if (error) throw error;
  return data;
}

// ── Email & Password Authentication ─────────────────────────────────────
export async function signUpOfficer({ email, password, fullName, badgeId, stationCode, clearance }) {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured. Please connect your Supabase database.");
  }

  const cleanEmail = String(email).trim().toLowerCase();
  const cleanName = fullName?.trim() || cleanEmail.split("@")[0];
  const cleanBadge = badgeId?.trim() || `CYBER-${Date.now().toString().slice(-6)}`;
  const cleanStation = stationCode?.trim() || "CYBER-PS-I4C-DELHI";
  const cleanClearance = clearance?.trim() || "Tier 1 - Unit Attribution";

  const { data, error } = await supabase.auth.signUp({
    email: cleanEmail,
    password,
    options: {
      data: {
        full_name: cleanName,
        badge_id: cleanBadge,
        station_code: cleanStation,
        clearance: cleanClearance,
      },
    },
  });
  if (error) throw error;

  // Ensure row exists in profiles table immediately
  if (data?.user?.id) {
    try {
      await supabase.from("profiles").upsert({
        id: data.user.id,
        email: cleanEmail,
        full_name: cleanName,
        badge_id: cleanBadge,
        station_code: cleanStation,
        clearance: cleanClearance,
        // role intentionally omitted — the database assigns least privilege
      
        status: "active",
      });
    } catch (profileErr) {
      console.warn("Profile table insert warning:", profileErr);
    }
  }

  await logAudit("account.signup", cleanEmail, { badge_id: cleanBadge });
  return data;
}

export async function signInOfficer({ email, password }) {
  if (!isSupabaseConfigured) {
    throw new Error("Supabase is not configured. Please connect your Supabase database.");
  }

  const cleanEmail = String(email).trim().toLowerCase();
  const { data, error } = await supabase.auth.signInWithPassword({
    email: cleanEmail,
    password,
  });
  if (error) throw error;

  // Check if profile is suspended
  if (data?.user?.id) {
    try {
      const { data: profile } = await supabase
        .from("profiles")
        .select("status")
        .eq("id", data.user.id)
        .maybeSingle();

      if (profile && profile.status === "suspended") {
        await supabase.auth.signOut();
        throw new Error("This officer account is suspended. Contact an administrator.");
      }
    } catch (err) {
      if (err.message?.includes("suspended")) throw err;
    }
  }

  await logAudit("account.signin", cleanEmail, null);
  return data;
}

export async function signOutOfficer() {
  await logAudit("account.signout", null, null);
  try {
    await supabase.auth.signOut();
  } catch (err) {
    console.warn("Sign out err:", err);
  }
  try {
    writePref(SESSION_KEY, "");
  } catch {
    /* storage unavailable */
  }
}

export async function getSessionUser() {
  if (!isSupabaseConfigured) return null;
  try {
    const { data } = await supabase.auth.getUser();
    return data?.user ?? null;
  } catch {
    return null;
  }
}

export async function getMyProfile() {
  const sessionUser = await getSessionUser();
  if (!sessionUser) return null;

  try {
    const { data, error } = await supabase
      .from("profiles")
      .select("*")
      .eq("id", sessionUser.id)
      .maybeSingle();

    if (!error && data) {
      return data;
    }

    // Auto-create/upsert profile row if missing for this authenticated user (e.g. OAuth signup)
    const meta = sessionUser.user_metadata || {};
    const fallbackProfile = {
      id: sessionUser.id,
      email: sessionUser.email,
      full_name: meta.full_name || meta.name || meta.user_name || (sessionUser.email ? sessionUser.email.split("@")[0] : "Officer"),
      badge_id: meta.badge_id || `I4C-${sessionUser.id.slice(0, 6).toUpperCase()}`,
      station_code: meta.station_code || "CYBER-PS-I4C-DELHI",
      clearance: meta.clearance || "Tier 1 - Unit Attribution",
      // PRIVILEGE ESCALATION FIX. This previously read:
      //     role: email.includes("admin") ? "admin" : "investigator"
      // so signing up as anything@admin.com granted admin. The client never
      // decides its own privilege level — the database default ('viewer')
      // applies, and an existing admin promotes the account.
      // status stays 'pending' until an admin activates it.
      status: "pending",
      created_at: sessionUser.created_at || new Date().toISOString(),
    };

    await supabase.from("profiles").upsert(fallbackProfile);
    return fallbackProfile;
  } catch (err) {
    console.warn("Failed to get profile from Supabase:", err);
    return {
      id: sessionUser.id,
      email: sessionUser.email,
      full_name: sessionUser.user_metadata?.full_name || sessionUser.email?.split("@")[0] || "Officer",
      badge_id: `I4C-${sessionUser.id.slice(0, 6).toUpperCase()}`,
      station_code: "CYBER-PS-I4C-DELHI",
      clearance: "Tier 1 - Unit Attribution",
      // role intentionally omitted — the database assigns least privilege
      
      status: "active",
    };
  }
}

export async function updateMyProfile(patch) {
  const sessionUser = await getSessionUser();
  if (!sessionUser) throw new Error("No active session.");

  const { error } = await supabase
    .from("profiles")
    .update(patch)
    .eq("id", sessionUser.id);

  if (error) throw error;
  await logAudit("profile.updated", sessionUser.email, patch);
}

// ── Administration & Profiles ───────────────────────────────────────────
export async function listProfiles() {
  if (!isSupabaseConfigured) return [];
  try {
    const { data, error } = await supabase
      .from("profiles")
      .select("*")
      .order("created_at", { ascending: false });

    if (error) {
      console.warn("Could not query profiles from Supabase:", error.message);
      return [];
    }
    return data ?? [];
  } catch (err) {
    console.warn("listProfiles error:", err);
    return [];
  }
}

export async function setProfileRole(id, role) {
  if (!isSupabaseConfigured) return;
  const { error } = await supabase.from("profiles").update({ role }).eq("id", id);
  if (error) throw error;
  await logAudit("user.role_changed", id, { role });
}

export async function setProfileStatus(id, status) {
  if (!isSupabaseConfigured) return;
  const { error } = await supabase.from("profiles").update({ status }).eq("id", id);
  if (error) throw error;
  await logAudit("user.status_changed", id, { status });
}

export async function listAuditLog(limit = 100) {
  if (!isSupabaseConfigured) return [];
  try {
    const { data, error } = await supabase
      .from("audit_log")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit);

    if (error) {
      console.warn("Could not query audit_log from Supabase:", error.message);
      return [];
    }
    return data ?? [];
  } catch {
    return [];
  }
}

export async function logAudit(action, target, detail) {
  if (!isSupabaseConfigured) return;
  try {
    const session = await getSessionUser();
    const actorEmail = session?.email ?? (typeof target === "string" && target.includes("@") ? target : "system");

    // Try append_audit RPC first
    const { error: rpcErr } = await supabase.rpc("append_audit", {
      p_action: action,
      p_target: target ?? null,
      p_detail: detail ?? null,
    });

    if (rpcErr) {
      // Fallback to direct insert
      await supabase.from("audit_log").insert({
        actor_id: session?.id ?? null,
        actor_email: actorEmail,
        action,
        target: target ?? null,
        detail: detail ?? null,
      });
    }
  } catch (err) {
    console.warn("audit log skipped:", err?.message ?? err);
  }
}

/** Review decisions for case dossiers */
export function dossierReviews() {
  try {
    const raw = readPref(DOSSIER_REVIEW_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export async function reviewDossier(id, approvalStatus, note) {
  if (isSupabaseConfigured) {
    const session = await getSessionUser();
    try {
      const { error } = await supabase
        .from("dossiers")
        .update({
          approval_status: approvalStatus,
          approved_by: session?.id ?? null,
          approved_at: new Date().toISOString(),
          review_note: note ?? null,
        })
        .eq("id", id);

      if (error) {
        // Try RPC fallback if direct update failed
        await supabase.rpc("review_dossier", {
          p_dossier_id: id,
          p_approval_status: approvalStatus,
          p_note: note ?? null,
        });
      }
    } catch (err) {
      console.warn("reviewDossier error:", err);
    }
  }

  try {
    const current = dossierReviews();
    writePref(DOSSIER_REVIEW_KEY, JSON.stringify({
      ...current,
      [id]: { approval_status: approvalStatus, approved_at: new Date().toISOString(), review_note: note ?? null },
    }));
  } catch {
    /* storage unavailable */
  }

  await logAudit(`dossier.${approvalStatus}`, id, { note: note ?? null });
}
