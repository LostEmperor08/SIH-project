import React, { useState, useEffect } from "react";
import {
  ArrowRight,
  Bell,
  CheckCircle2,
  Clock3,
  ShieldAlert,
  Radio,
  FileCheck2,
  ExternalLink,
  CheckCheck,
  Filter,
  Sparkles,
  Zap,
} from "lucide-react";

const INITIAL_NOTIFICATIONS = [
  {
    id: "notif-1",
    category: "attribution",
    type: "CRITICAL",
    unread: true,
    title: "High-Confidence VASP Attribution Match",
    description: "Wallet 0x71C...829a attributed to WazirX Exploit Co-Conspirator cluster with 96.4% confidence score across 4 hop traces.",
    time: "2 minutes ago",
    target: "workspace",
    actionLabel: "Open Graph Trace",
  },
  {
    id: "notif-2",
    category: "evidence",
    type: "URGENT",
    unread: true,
    title: "Section 91 BNSS Preservation Window Countdown",
    description: "Statutory 72-hour freezing notice window for Binance India cold deposit address 0x93f...b1 expires in 2 hours 45 minutes.",
    time: "18 minutes ago",
    target: "dossier",
    actionLabel: "Generate S91 Notice",
  },
  {
    id: "notif-3",
    category: "watchlist",
    type: "SIGNAL",
    unread: true,
    title: "Watchlist Address Sudden Velocity Spike",
    description: "Target address TX7sK...91b transferred 145,000 USDT through an unauthorized Bridge contract (Hop Exchange).",
    time: "42 minutes ago",
    target: "watchlist",
    actionLabel: "Inspect Pulse",
  },
  {
    id: "notif-4",
    category: "system",
    type: "RESOLVED",
    unread: false,
    title: "Consensus Node Telemetry Resync Completed",
    description: "All 12 national attribution node clusters (Polygon, TRON, Ethereum, Arbitrum) successfully synced ledger state.",
    time: "1 hour ago",
    target: "workspace",
    actionLabel: "View Topology",
  },
  {
    id: "notif-5",
    category: "evidence",
    type: "COMPLETED",
    unread: false,
    title: "Cryptographic Certificate Generated (Sec 65B)",
    description: "Evidence Hash SHA-256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 sealed for FIR #402/24.",
    time: "3 hours ago",
    target: "dossier",
    actionLabel: "Download Dossier",
  },
  {
    id: "notif-6",
    category: "attribution",
    type: "SIGNAL",
    unread: false,
    title: "New Mule Account Ring Identified",
    description: "Coordinated peel chain detected across 6 UPI-linked domestic off-ramps in Delhi NCR region.",
    time: "5 hours ago",
    target: "workspace",
    actionLabel: "Analyze Ring",
  },
];

import { getAlerts, acknowledgeAlert, resolveAlert, dismissAlert, connectAlertsWebSocket } from "../lib/api.js";

export function NotificationsPage({ onNavigate }) {
  const [filter, setFilter] = useState("all");
  const [notifs, setNotifs] = useState(INITIAL_NOTIFICATIONS);
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    let alive = true;
    getAlerts({ limit: 100 })
      .then((liveAlerts) => {
        if (!alive || !Array.isArray(liveAlerts) || liveAlerts.length === 0) return;
        const mapped = liveAlerts.map((a) => ({
          id: a.id,
          category: a.alert_type?.includes("VASP") || a.alert_type?.includes("EXCHANGE") ? "attribution" : a.alert_type?.includes("SANCTION") ? "evidence" : "watchlist",
          type: a.severity || "MEDIUM",
          unread: a.status === "NEW",
          title: a.title,
          description: a.summary,
          time: new Date(a.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
          target: "workspace",
          actionLabel: "Open Money Trail",
          raw: a,
        }));
        setNotifs((prev) => [...mapped, ...prev.filter((p) => !mapped.some((m) => m.id === p.id))]);
        setIsLive(true);
      })
      .catch(() => {});

    const ws = connectAlertsWebSocket((newAlert) => {
      if (!alive || !newAlert) return;
      const mappedNew = {
        id: newAlert.id,
        category: "attribution",
        type: newAlert.severity || "HIGH",
        unread: true,
        title: newAlert.title,
        description: newAlert.summary,
        time: "Just now",
        target: "workspace",
        actionLabel: "Open Money Trail",
        raw: newAlert,
      };
      setNotifs((prev) => [mappedNew, ...prev]);
      setIsLive(true);
    });

    return () => {
      alive = false;
      if (ws) ws.close();
    };
  }, []);

  const unreadCount = notifs.filter((n) => n.unread).length;

  const filteredNotifs = notifs.filter((n) => {
    if (filter === "all") return true;
    if (filter === "unread") return n.unread;
    return n.category === filter;
  });

  const markAllRead = () => {
    setNotifs((prev) => prev.map((n) => ({ ...n, unread: false })));
  };

  const handleAction = async (id, actionType) => {
    setNotifs((prev) =>
      prev.map((n) => (n.id === id ? { ...n, unread: false, type: actionType === "acknowledge" ? "ACKNOWLEDGED" : "RESOLVED" } : n))
    );
    try {
      if (actionType === "acknowledge") await acknowledgeAlert(id);
      else if (actionType === "resolve") await resolveAlert(id);
      else if (actionType === "dismiss") await dismissAlert(id);
    } catch (e) {
      console.warn("Alert action failed:", e);
    }
  };

  return (
    <div className="space-y-6 pt-4 route-page-animated">
      {/* Hero Header Card */}
      <div className="glass-panel relative overflow-hidden rounded-2xl p-6 sm:p-8 shadow-2xl border border-[#E5B83B]/20">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 relative z-10">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-[#E5B83B]/10 border border-[#E5B83B]/30 px-3 py-1 text-xs font-bold text-[#E5B83B] mb-3">
              <Bell size={13} className="animate-pulse text-[#E5B83B]" />
              <span>I4C INTELLIGENCE & TELEMETRY STREAM</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-slate-900 dark:text-white">
              Operations & Attribution Signals
            </h1>
            <p className="mt-1 text-xs sm:text-sm text-slate-600 dark:text-slate-400 max-w-2xl font-medium">
              Real-time cryptographic alerts, statutory Section 91 preservation countdowns, and automated blockchain attribution signals.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="rolex-outline-btn inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-bold cursor-pointer"
              >
                <CheckCheck size={14} className="text-[#E5B83B]" />
                <span>Mark All Read</span>
              </button>
            )}

            <button
              type="button"
              onClick={() => onNavigate?.("workspace")}
              className="rolex-gold-btn inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-xs font-black cursor-pointer shadow-lg"
            >
              <span>Live Attribution</span>
              <ArrowRight size={14} className="text-[#150F00]" />
            </button>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="mt-6 flex flex-wrap items-center gap-2 pt-4 border-t border-slate-200 dark:border-white/10">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-500 mr-2">
            <Filter size={13} />
            <span>Filter:</span>
          </div>

          {[
            { id: "all", label: `All Signals (${notifs.length})` },
            { id: "unread", label: `Unread (${unreadCount})` },
            { id: "attribution", label: "Attribution Matches" },
            { id: "evidence", label: "Legal Notices" },
            { id: "watchlist", label: "Watchlist Alerts" },
          ].map((tab) => {
            const active = filter === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setFilter(tab.id)}
                className={`rounded-xl px-3.5 py-1.5 text-xs font-bold transition-all cursor-pointer ${
                  active
                    ? "bg-[#E5B83B] text-[#150F00] shadow-[0_2px_10px_rgba(229,184,59,0.35)]"
                    : "bg-slate-100 hover:bg-slate-200 dark:bg-white/5 dark:hover:bg-white/10 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-white/10"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Notifications List */}
      <div className="space-y-3">
        {filteredNotifs.length === 0 ? (
          <div className="glass-panel rounded-2xl p-12 text-center">
            <CheckCircle2 size={40} className="mx-auto text-emerald-500 mb-3" />
            <h3 className="text-base font-bold text-slate-900 dark:text-white">All Signals Acknowledged</h3>
            <p className="text-xs text-slate-500 mt-1">No unread alerts matching your current filter selection.</p>
          </div>
        ) : (
          filteredNotifs.map((item) => (
            <div
              key={item.id}
              onClick={() => markSingleRead(item.id)}
              className={`glass-panel group relative flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 rounded-2xl p-5 transition-all duration-200 hover:translate-x-1 cursor-pointer ${
                item.unread
                  ? "border-l-4 border-l-[#E5B83B] border-t border-r border-b border-slate-200 dark:border-white/15 bg-amber-500/[0.02]"
                  : "border border-slate-200 dark:border-white/10 opacity-90"
              }`}
            >
              <div className="flex items-start gap-4">
                <div
                  className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${
                    item.category === "attribution"
                      ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-400"
                      : item.category === "evidence"
                      ? "bg-amber-500/15 border-amber-500/30 text-amber-400"
                      : "bg-sky-500/15 border-sky-500/30 text-sky-400"
                  }`}
                >
                  {item.category === "attribution" && <Zap size={18} />}
                  {item.category === "evidence" && <FileCheck2 size={18} />}
                  {item.category === "watchlist" && <Radio size={18} />}
                  {item.category === "system" && <Sparkles size={18} />}
                </div>

                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white group-hover:text-[#E5B83B] transition-colors">
                      {item.title}
                    </h3>
                    {item.unread && (
                      <span className="rounded-full bg-[#E5B83B]/20 border border-[#E5B83B]/40 px-2 py-0.2 text-[9px] font-extrabold text-[#B45309] dark:text-[#FFE28A]">
                        UNREAD
                      </span>
                    )}
                    <span
                      className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${
                        item.type === "CRITICAL"
                          ? "bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30"
                          : item.type === "URGENT"
                          ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30"
                          : "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30"
                      }`}
                    >
                      {item.type}
                    </span>
                  </div>

                  <p className="text-xs text-slate-600 dark:text-slate-400 max-w-3xl leading-relaxed">
                    {item.description}
                  </p>

                  <div className="flex items-center gap-2 pt-1 text-[11px] text-slate-500 dark:text-slate-400 font-medium">
                    <Clock3 size={12} className="text-[#E5B83B]" />
                    <span>{item.time}</span>
                    <span>•</span>
                    <span className="capitalize">{item.category} Intelligence</span>
                  </div>
                </div>
              </div>

              <div className="flex sm:flex-col items-center sm:items-end justify-between w-full sm:w-auto gap-2 shrink-0 pt-2 sm:pt-0 border-t sm:border-0 border-slate-200 dark:border-white/5">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    markSingleRead(item.id);
                    onNavigate?.(item.target);
                  }}
                  className="rolex-outline-btn flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold text-slate-800 dark:text-slate-200 hover:text-[#E5B83B] cursor-pointer whitespace-nowrap"
                >
                  <span>{item.actionLabel}</span>
                  <ExternalLink size={12} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
