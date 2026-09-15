import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2, ChevronRight, FileText, Loader2, RefreshCw,
  ScrollText, ShieldAlert, ShieldCheck, Users, XCircle,
} from "lucide-react";
import { listProfiles, setProfileRole, setProfileStatus, listAuditLog, reviewDossier, dossierReviews } from "../lib/auth.js";
import { fetchDossiers } from "../lib/supabase.js";

const ROLES = ["admin", "investigator", "viewer"];
const STATUSES = ["active", "pending", "suspended"];

const TABS = [
  { id: "users", label: "Users & roles", icon: Users },
  { id: "review", label: "Case review", icon: FileText },
  { id: "audit", label: "Audit log", icon: ScrollText },
];

const panel = "glass-panel admin-panel rounded-2xl";
const cell = "px-4 py-3 text-xs";
const head = "px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-left admin-th";

function Pill({ tone, children }) {
  return <span className="status-chip" data-state={tone}>{children}</span>;
}

export function AdminPanel({ profile }) {
  const [tab, setTab] = useState("users");
  const [users, setUsers] = useState([]);
  const [dossiers, setDossiers] = useState([]);
  const [audit, setAudit] = useState([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(null);

  const isAdmin = profile?.role === "admin";

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    const results = await Promise.allSettled([listProfiles(), fetchDossiers(), listAuditLog(120)]);
    if (results[0].status === "fulfilled") setUsers(results[0].value);
    if (results[1].status === "fulfilled") {
      const reviews = dossierReviews();
      setDossiers(results[1].value.map((d) => ({ ...d, ...(reviews[d.id] ?? {}) })));
    }
    if (results[2].status === "fulfilled") setAudit(results[2].value);
    const failed = results.find((r) => r.status === "rejected");
    if (failed) setError(failed.reason?.message ?? "Some admin data could not be loaded.");
    setBusy(false);
  }, []);

  useEffect(() => {
    if (isAdmin) load();
    else setBusy(false);
  }, [isAdmin, load]);

  const pendingCount = useMemo(
    () => dossiers.filter((d) => (d.approval_status ?? "pending") === "pending").length,
    [dossiers],
  );

  async function mutate(fn) {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err?.message ?? "Change failed");
    }
  }

  if (!isAdmin) {
    return (
      <div className={`${panel} mx-auto max-w-xl p-10 text-center`}>
        <ShieldAlert size={26} className="mx-auto admin-accent" />
        <h2 className="mt-3 text-lg font-extrabold">Administrator clearance required</h2>
        <p className="mt-2 text-xs admin-muted">
          Your account is signed in as <strong>{profile?.role ?? "guest"}</strong>. Ask an existing administrator to
          raise your role on the Users &amp; roles screen.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <header className={`${panel} flex flex-wrap items-center justify-between gap-4 p-5`}>
        <div>
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider admin-accent">
            <ShieldCheck size={14} /> Administration
          </div>
          <h1 className="mt-1 text-xl font-extrabold tracking-tight">Command console</h1>
          <p className="mt-1 text-xs admin-muted">
            {users.length} accounts · {pendingCount} dossiers awaiting review · {audit.length} logged actions
          </p>
        </div>
        <button type="button" onClick={load} className="admin-btn flex items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-bold">
          {busy ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </header>

      {error && (
        <div className="admin-warn rounded-xl p-3 text-xs font-semibold">
          {error} — if this mentions a missing table, run <code>supabase-setup.sql</code> in your Supabase SQL editor.
        </div>
      )}

      <nav className="flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`admin-tab ${tab === id ? "is-active" : ""} flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold`}
          >
            <Icon size={14} /> {label}
            {id === "review" && pendingCount > 0 && <span className="admin-count">{pendingCount}</span>}
          </button>
        ))}
      </nav>

      {tab === "users" && (
        <section className={`${panel} table-scroll overflow-x-auto`}>
          <table className="w-full min-w-[720px] border-collapse">
            <thead className="admin-thead">
              <tr>
                <th className={head}>Officer</th>
                <th className={head}>Badge / unit</th>
                <th className={head}>Role</th>
                <th className={head}>Status</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="admin-tr">
                  <td className={cell}>
                    <div className="font-bold">{u.full_name ?? "—"}</div>
                    <div className="font-mono text-[11px] admin-muted">{u.email}</div>
                  </td>
                  <td className={`${cell} font-mono text-[11px]`}>
                    <div>{u.badge_id ?? "—"}</div>
                    <div className="admin-muted">{u.station_code ?? "—"}</div>
                  </td>
                  <td className={cell}>
                    <select
                      value={u.role}
                      onChange={(e) => mutate(() => setProfileRole(u.id, e.target.value))}
                      className="admin-select rounded-lg px-2 py-1 text-[11px] font-bold"
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td className={cell}>
                    <div className="flex items-center gap-2">
                      <Pill tone={u.status}>{u.status}</Pill>
                      {STATUSES.filter((s) => s !== u.status).map((s) => (
                        <button key={s} type="button" onClick={() => mutate(() => setProfileStatus(u.id, s))} className="admin-btn px-2 py-1 text-[10px] font-bold">
                          Set {s}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {!users.length && !busy && (
                <tr><td className={`${cell} text-center admin-muted`} colSpan={4}>No accounts yet. The profiles table fills as officers register.</td></tr>
              )}
            </tbody>
          </table>
        </section>
      )}

      {tab === "review" && (
        <section className="grid gap-3 md:grid-cols-2">
          {dossiers.map((d) => {
            const status = d.approval_status ?? "pending";
            return (
              <article key={d.id} className={`${panel} p-5`}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-mono text-[11px] admin-muted">{d.case_ref}</div>
                    <h3 className="mt-1 text-sm font-extrabold">{d.title}</h3>
                  </div>
                  <Pill tone={status}>{status}</Pill>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px] admin-muted">
                  <div><dt className="font-bold">VASP</dt><dd>{d.target_vasp}</dd></div>
                  <div><dt className="font-bold">Traced</dt><dd>₹{Number(d.total_traced_inr ?? 0).toLocaleString()}</dd></div>
                  <div><dt className="font-bold">Confidence</dt><dd>{d.confidence}</dd></div>
                  <div><dt className="font-bold">Officer</dt><dd>{d.io_name}</dd></div>
                </dl>
                <div className="mt-4 flex gap-2">
                  <button type="button" onClick={() => mutate(() => reviewDossier(d.id, "approved"))} className="admin-approve flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-bold">
                    <CheckCircle2 size={14} /> Approve
                  </button>
                  <button type="button" onClick={() => mutate(() => reviewDossier(d.id, "rejected"))} className="admin-reject flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-bold">
                    <XCircle size={14} /> Reject
                  </button>
                </div>
              </article>
            );
          })}
          {!dossiers.length && !busy && <div className={`${panel} p-8 text-center text-xs admin-muted`}>No dossiers submitted yet.</div>}
        </section>
      )}

      {tab === "audit" && (
        <section className={panel}>
          {audit.map((row) => (
            <div key={row.id} className="admin-tr flex items-start gap-3 p-4">
              <ChevronRight size={14} className="mt-0.5 shrink-0 admin-accent" />
              <div className="min-w-0 flex-1">
                <div className="font-mono text-xs font-bold">{row.action}</div>
                <div className="truncate text-[11px] admin-muted">
                  {row.actor_email ?? "system"} {row.target ? `→ ${row.target}` : ""}
                </div>
              </div>
              <time className="shrink-0 font-mono text-[10px] admin-muted">{new Date(row.created_at).toLocaleString()}</time>
            </div>
          ))}
          {!audit.length && !busy && (
            <div className="p-8 text-center text-xs admin-muted">
              No actions logged yet. Sign-ins, role changes and dossier reviews land here.
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default AdminPanel;
