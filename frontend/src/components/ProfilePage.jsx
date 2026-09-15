import React, { useEffect, useState } from "react";
import { BadgeCheck, Building2, Check, Fingerprint, LogOut, Mail, Moon, Pencil, ShieldCheck, Sun } from "lucide-react";
import { getMyProfile, signOutOfficer, updateMyProfile } from "../lib/auth.js";

const CLEARANCES = [
  "Tier 1 - Unit Attribution",
  "Tier 2 - National Attribution",
  "Tier 3 - Cross-Border / FIU",
];

const panel = "glass-panel admin-panel rounded-2xl";

function Field({ icon: Icon, label, value, onChange, editing, mono, options }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider admin-muted">
        <Icon size={12} className="admin-accent" /> {label}
      </span>
      {editing ? (
        options ? (
          <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} className="admin-select w-full rounded-xl px-3 py-2.5 text-xs font-bold">
            {options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        ) : (
          <input value={value ?? ""} onChange={(e) => onChange(e.target.value)} className={`admin-select w-full rounded-xl px-3 py-2.5 text-xs font-bold ${mono ? "font-mono" : ""}`} />
        )
      ) : (
        <span className={`block text-sm font-bold ${mono ? "font-mono text-xs" : ""}`}>{value || "—"}</span>
      )}
    </label>
  );
}

export function ProfilePage() {
  const [profile, setProfile] = useState(null);
  const [draft, setDraft] = useState({});
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    getMyProfile()
      .then((p) => {
        if (!alive) return;
        setProfile(p);
        setDraft(p ?? {});
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, []);

  async function save() {
    setError(null);
    try {
      const patch = {
        full_name: draft.full_name,
        badge_id: draft.badge_id,
        station_code: draft.station_code,
        clearance: draft.clearance,
      };
      await updateMyProfile(patch);
      setProfile({ ...profile, ...patch });
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2200);
    } catch (e) {
      setError(e.message ?? "Could not save");
    }
  }

  if (!profile) {
    return (
      <div className={`${panel} mx-auto max-w-md p-10 text-center`}>
        <p className="text-xs font-bold admin-muted">{error ? error : "No active session. Sign in to view your officer profile."}</p>
        <a href="/login" className="admin-btn mt-4 inline-flex rounded-xl px-4 py-2 text-xs font-bold">Go to sign in</a>
      </div>
    );
  }

  const initials = (profile.full_name ?? profile.email ?? "?")
    .split(/[\s.@]/).filter(Boolean).slice(0, 2).map((s) => s[0].toUpperCase()).join("");

  return (
    <div className="mx-auto grid w-full max-w-5xl gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
      <aside className={`${panel} h-fit p-6 text-center`}>
        <div className="profile-avatar-tile mx-auto grid h-20 w-20 place-items-center rounded-2xl text-2xl font-extrabold">{initials}</div>
        <h1 className="mt-4 text-lg font-extrabold tracking-tight">{profile.full_name ?? "Unnamed officer"}</h1>
        <p className="font-mono text-[11px] admin-muted">{profile.email}</p>

        <div className="mt-3 flex flex-wrap justify-center gap-2">
          <Pill>{profile.role}</Pill>
          <span className="admin-pill admin-pill--active">{profile.status}</span>
        </div>

        <div className="mt-6 space-y-2 text-left">
          {profile.role === "admin" && (
            <a href="/admin" className="admin-btn flex w-full items-center gap-2 rounded-xl px-3.5 py-2.5 text-xs font-bold">
              <ShieldCheck size={14} /> Admin console
            </a>
          )}
          <button type="button" onClick={() => signOutOfficer().then(() => (window.location.href = "/login"))} className="admin-reject flex w-full items-center gap-2 rounded-xl px-3.5 py-2.5 text-xs font-bold">
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      <section className={`${panel} p-6`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider admin-accent">
              <ShieldCheck size={13} /> Agency record
            </div>
            <h2 className="mt-1 text-base font-extrabold">Officer credentials</h2>
          </div>
          {editing ? (
            <div className="flex gap-2">
              <button type="button" onClick={() => { setDraft(profile); setEditing(false); }} className="admin-row rounded-xl px-3 py-2 text-xs font-bold">Cancel</button>
              <button type="button" onClick={save} className="admin-primary rounded-xl px-4 py-2 text-xs font-extrabold">Save changes</button>
            </div>
          ) : (
            <button type="button" onClick={() => setEditing(true)} className="admin-btn flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-bold">
              <Pencil size={13} /> Edit
            </button>
          )}
        </div>

        {saved && <div className="admin-approve mt-4 flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-bold"><Check size={14} /> Profile saved</div>}
        {error && <div className="admin-reject mt-4 rounded-xl px-3 py-2 text-xs font-bold">{error}</div>}

        <div className="mt-6 grid gap-5 sm:grid-cols-2">
          <Field icon={BadgeCheck} label="Full name" value={draft.full_name} editing={editing} onChange={(v) => setDraft({ ...draft, full_name: v })} />
          <Field icon={Mail} label="Email" value={profile.email} editing={false} mono />
          <Field icon={Fingerprint} label="Badge / service ID" value={draft.badge_id} editing={editing} mono onChange={(v) => setDraft({ ...draft, badge_id: v })} />
          <Field icon={Building2} label="Station / unit code" value={draft.station_code} editing={editing} mono onChange={(v) => setDraft({ ...draft, station_code: v })} />
          <Field icon={ShieldCheck} label="Clearance tier" value={draft.clearance} editing={editing} options={CLEARANCES} onChange={(v) => setDraft({ ...draft, clearance: v })} />
          <Field icon={Sparkles} label="Account created" editing={false} value={profile.created_at ? new Date(profile.created_at).toLocaleDateString() : "—"} />
        </div>
      </section>
    </div>
  );
}

function Pill({ children }) {
  return <span className="admin-pill admin-pill--admin">{children}</span>;
}

export default ProfilePage;
