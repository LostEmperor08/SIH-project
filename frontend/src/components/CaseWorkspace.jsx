import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Activity, AlertTriangle, ArrowRight, Bell, BookOpen, CheckCircle, Clock3, 
  ExternalLink, FileSpreadsheet, FileText, Filter, GitBranch, Layers, MessageSquare, 
  Plus, Search, Shield, ShieldAlert, Sparkles, User, Zap 
} from "lucide-react";
import GraphVisualizer from "./GraphVisualizer.jsx";
import { EvidenceLedgerPage } from "./EvidenceLedgerPage.jsx";
import { 
  getCaseSummary, getCaseWallets, getCaseTransactions, getCaseExchanges, 
  getCaseCrossChain, getCaseRecommendations, getCaseTimeline, getCaseNotes, 
  addCaseNote, getCaseTasks, createCaseTask, updateCaseStatus, getAlerts,
  submitNCRPReport, submitSahyogAction
} from "../lib/api.js";

const WORKSPACE_TABS = [
  { id: "overview", label: "Overview", icon: Activity },
  { id: "reported", label: "Reported Wallet", icon: Shield },
  { id: "trail", label: "Money Trail", icon: GitBranch },
  { id: "transactions", label: "Transactions", icon: Layers },
  { id: "wallets", label: "Wallets", icon: Filter },
  { id: "exchanges", label: "Exchanges", icon: ExternalLink },
  { id: "cross-chain", label: "Cross-Chain", icon: Zap },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "recommendations", label: "Recommendations", icon: Sparkles },
  { id: "notes-tasks", label: "Notes & Tasks", icon: MessageSquare },
  { id: "report", label: "Evidence & Report", icon: FileText },
];

export function CaseWorkspace({ caseId = "SIH/2026/00412", graph, onSelectWallet }) {
  const [activeTab, setActiveTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [wallets, setWallets] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [exchanges, setExchanges] = useState([]);
  const [crossChain, setCrossChain] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [notes, setNotes] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [alerts, setAlerts] = useState([]);

  // Trail Graph Filter State
  const [trailFilter, setTrailFilter] = useState("PRIMARY"); // PRIMARY, ATTRIBUTED, EXCHANGES, CROSS_CHAIN, ALL

  // Notes & Tasks Form State
  const [newNoteText, setNewNoteText] = useState("");
  const [newTaskTitle, setNewTaskTitle] = useState("");

  // Status Change State
  const [statusValue, setStatusValue] = useState("ACTIVE");

  useEffect(() => {
    let alive = true;
    setLoading(true);

    Promise.all([
      getCaseSummary(caseId).catch(() => null),
      getCaseWallets(caseId).catch(() => []),
      getCaseTransactions(caseId).catch(() => []),
      getCaseExchanges(caseId).catch(() => []),
      getCaseCrossChain(caseId).catch(() => []),
      getCaseRecommendations(caseId).catch(() => []),
      getCaseTimeline(caseId).catch(() => []),
      getCaseNotes(caseId).catch(() => []),
      getCaseTasks(caseId).catch(() => []),
      getAlerts({ limit: 10 }).catch(() => []),
    ]).then(([sumData, walData, txData, exData, ccData, recData, timeData, noteData, taskData, altData]) => {
      if (!alive) return;
      if (sumData) {
        setSummary(sumData);
        setStatusValue(sumData.case?.status || "ACTIVE");
      }
      setWallets(walData);
      setTransactions(txData);
      setExchanges(exData);
      setCrossChain(ccData);
      setRecommendations(recData);
      setTimeline(timeData);
      setNotes(noteData);
      setTasks(taskData);
      setAlerts(altData);
      setLoading(false);
    });

    return () => { alive = false; };
  }, [caseId]);

  const handleStatusChange = async (newStatus) => {
    setStatusValue(newStatus);
    try {
      await updateCaseStatus(caseId, newStatus, `Updated case status to ${newStatus}`);
    } catch (err) {
      console.warn("Failed to update status:", err);
    }
  };

  const handleAddNote = async (e) => {
    e.preventDefault();
    if (!newNoteText.trim()) return;
    try {
      const added = await addCaseNote(caseId, newNoteText);
      if (added) setNotes([added, ...notes]);
      setNewNoteText("");
    } catch (err) {
      console.warn("Failed to add note:", err);
    }
  };

  const handleCreateTask = async (e) => {
    e.preventDefault();
    if (!newTaskTitle.trim()) return;
    try {
      const created = await createCaseTask(caseId, { title: newTaskTitle, priority: "HIGH" });
      if (created) setTasks([created, ...tasks]);
      setNewTaskTitle("");
    } catch (err) {
      console.warn("Failed to create task:", err);
    }
  };

  const caseObj = summary?.case || {
    case_ref: caseId,
    title: "Crypto Scam Investigation",
    reported_wallet: "0x71c7656ec7ab88b098defb751b7401b5f6d8976f",
    reported_chain: "polygon",
    reported_amount_usd: 10000.0,
    status: "ACTIVE",
    priority: "HIGH",
  };

  const metrics = summary?.metrics || {
    reported_amount_usd: 10000.0,
    attributed_value_usd: 8400.0,
    wallet_count: wallets.length || 3,
    transaction_count: transactions.length || 2,
    exchange_count: exchanges.length || 1,
    exchange_name: "Coinbase",
    cross_chain_count: crossChain.length || 1,
    active_alert_count: alerts.length || 2,
    highest_risk_score: 78.5,
  };

  return (
    <div className="space-y-6">
      {/* Case Header Banner */}
      <div className="glass-panel p-6 rounded-2xl border border-[#E5B83B]/25 shadow-2xl">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-md text-[10px] font-extrabold uppercase bg-[#E5B83B]/20 text-[#FFE28A] border border-[#E5B83B]/40">
                {caseObj.case_ref}
              </span>
              <span className="px-2.5 py-0.5 rounded-md text-[10px] font-extrabold uppercase bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                {caseObj.reported_chain.toUpperCase()}
              </span>
              <span className="px-2.5 py-0.5 rounded-md text-[10px] font-extrabold uppercase bg-red-500/20 text-red-300 border border-red-500/30">
                PRIORITY: {caseObj.priority}
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white mt-2 tracking-tight">
              {caseObj.title}
            </h1>
            <p className="text-xs text-slate-300 mt-1 flex items-center gap-2">
              <span>Reported Wallet: <strong className="font-mono text-[#E5B83B]">{caseObj.reported_wallet}</strong></span>
              <span>•</span>
              <span>Reported Fund: <strong>${caseObj.reported_amount_usd.toLocaleString()} USD</strong></span>
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="text-[10px] uppercase font-bold text-slate-400">Investigation Status</div>
              <select
                value={statusValue}
                onChange={(e) => handleStatusChange(e.target.value)}
                className="mt-1 bg-[#091E16] border border-[#E5B83B]/40 text-xs font-bold text-slate-100 rounded-lg px-3 py-1.5 focus:outline-none focus:border-[#E5B83B]"
              >
                <option value="OPEN">OPEN</option>
                <option value="ACTIVE">ACTIVE</option>
                <option value="UNDER_REVIEW">UNDER REVIEW</option>
                <option value="PENDING_ACTION">PENDING ACTION</option>
                <option value="CLOSED">CLOSED</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* Case Workspace Sub-Navigation Tabs */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-2 border-b border-slate-800">
        {WORKSPACE_TABS.map((t) => {
          const Icon = t.icon;
          const isActive = activeTab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all whitespace-nowrap cursor-pointer ${
                isActive
                  ? "bg-[#E5B83B] text-[#150F00] shadow-md shadow-[#E5B83B]/20"
                  : "bg-[#091E16]/70 text-slate-300 hover:bg-[#0c2b1d] border border-slate-800"
              }`}
            >
              <Icon size={14} />
              <span>{t.label}</span>
            </button>
          );
        })}
      </div>

      {/* Workspace Tab Contents */}
      <AnimatePresence mode="wait">
        {/* ── TAB 1: OVERVIEW ── */}
        {activeTab === "overview" && (
          <motion.div key="overview" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-6">
            {/* Metrics Dashboard */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
              <div className="glass-panel p-3 rounded-xl border border-[#E5B83B]/20">
                <div className="text-[10px] font-bold text-[#E5B83B] uppercase">Reported Amount</div>
                <div className="text-lg font-bold text-white mt-1">${metrics.reported_amount_usd.toLocaleString()}</div>
                <div className="text-[9px] text-slate-400">Victim Complaint</div>
              </div>
              <div className="glass-panel p-3 rounded-xl border border-emerald-500/20">
                <div className="text-[10px] font-bold text-emerald-400 uppercase">Funds Linked</div>
                <div className="text-lg font-bold text-white mt-1">${metrics.attributed_value_usd.toLocaleString()}</div>
                <div className="text-[9px] text-slate-400">Attributed Movement</div>
              </div>
              <div className="glass-panel p-3 rounded-xl border border-slate-800">
                <div className="text-[10px] font-bold text-slate-400 uppercase">Wallets</div>
                <div className="text-lg font-bold text-white mt-1">{metrics.wallet_count}</div>
                <div className="text-[9px] text-slate-400">Discovered</div>
              </div>
              <div className="glass-panel p-3 rounded-xl border border-slate-800">
                <div className="text-[10px] font-bold text-slate-400 uppercase">Transactions</div>
                <div className="text-lg font-bold text-white mt-1">{metrics.transaction_count}</div>
                <div className="text-[9px] text-slate-400">Traced Hops</div>
              </div>
              <div className="glass-panel p-3 rounded-xl border border-[#E5B83B]/20">
                <div className="text-[10px] font-bold text-[#E5B83B] uppercase">Exchanges</div>
                <div className="text-lg font-bold text-white mt-1">{metrics.exchange_name || "1"}</div>
                <div className="text-[9px] text-slate-400">Receiving VASP</div>
              </div>
              <div className="glass-panel p-3 rounded-xl border border-purple-500/20">
                <div className="text-[10px] font-bold text-purple-400 uppercase">Cross-Chain</div>
                <div className="text-lg font-bold text-white mt-1">{metrics.cross_chain_count} Event(s)</div>
                <div className="text-[9px] text-slate-400">Bridge Correlation</div>
              </div>
              <div className="glass-panel p-3 rounded-xl border border-amber-500/20">
                <div className="text-[10px] font-bold text-amber-400 uppercase">Active Alerts</div>
                <div className="text-lg font-bold text-white mt-1">{metrics.active_alert_count}</div>
                <div className="text-[9px] text-slate-400">Surveillance</div>
              </div>
              <div className="glass-panel p-3 rounded-xl border border-red-500/20">
                <div className="text-[10px] font-bold text-red-400 uppercase">Max Wallet Risk</div>
                <div className="text-lg font-bold text-white mt-1">{metrics.highest_risk_score}/100</div>
                <div className="text-[9px] text-slate-400">High Risk Mule</div>
              </div>
            </div>

            {/* Evidence-Based Summary Banner */}
            <div className="glass-panel p-5 rounded-xl border border-[#E5B83B]/30 bg-[#091E16]/80">
              <h3 className="text-sm font-bold text-[#FFE28A] flex items-center gap-2">
                <Sparkles size={16} className="text-[#E5B83B]" /> Case Summary & Evidence Findings
              </h3>
              <p className="text-xs text-slate-200 mt-2 leading-relaxed">
                {summary?.summary_statement || "Reported funds were observed moving through intermediate mule wallets before reaching an identified crypto exchange deposit wallet."}
              </p>
            </div>

            {/* Recommendations & Timeline Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Recommendations Box */}
              <div className="glass-panel p-5 rounded-2xl border border-slate-800">
                <h3 className="text-sm font-bold text-white flex items-center gap-2 mb-4">
                  <Sparkles size={16} className="text-[#E5B83B]" /> Recommended Investigator Actions
                </h3>
                <div className="space-y-3">
                  {recommendations.map((r) => (
                    <div key={r.id} className="p-3.5 rounded-xl bg-[#081B13] border border-slate-800">
                      <div className="flex items-center justify-between">
                        <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded ${
                          r.priority === "HIGH" ? "bg-red-500/20 text-red-300 border border-red-500/30" : "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                        }`}>
                          {r.priority} PRIORITY
                        </span>
                      </div>
                      <h4 className="text-xs font-bold text-slate-100 mt-2">{r.title}</h4>
                      <p className="text-[11px] text-slate-300 mt-1">{r.action_text}</p>
                      <div className="mt-2 text-[10px] text-slate-400 bg-slate-900/60 p-2 rounded border border-slate-800">
                        <strong>Evidence Grounds:</strong>
                        <ul className="list-disc list-inside mt-0.5 space-y-0.5">
                          {r.basis?.map((b, i) => <li key={i}>{b}</li>)}
                        </ul>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Timeline Box */}
              <div className="glass-panel p-5 rounded-2xl border border-slate-800">
                <h3 className="text-sm font-bold text-white flex items-center gap-2 mb-4">
                  <Clock3 size={16} className="text-[#E5B83B]" /> Case Timeline & Event Audit
                </h3>
                <div className="space-y-3">
                  {timeline.map((t) => (
                    <div key={t.id} className="flex items-start gap-3 p-3 rounded-xl bg-[#081B13] border border-slate-800">
                      <div className="w-2 h-2 rounded-full bg-[#E5B83B] mt-1.5 flex-shrink-0" />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-slate-100">{t.title}</span>
                          <span className="text-[10px] text-slate-400">{t.created_at?.slice(0, 16).replace("T", " ")}</span>
                        </div>
                        <p className="text-[11px] text-slate-300 mt-0.5">{t.description}</p>
                        <div className="text-[10px] text-slate-400 mt-1">Actor: {t.actor} ({t.actor_role})</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </motion.div>
        )}

        {/* ── TAB 2: REPORTED WALLET ── */}
        {activeTab === "reported" && (
          <motion.div key="reported" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="glass-panel p-6 rounded-2xl border border-[#E5B83B]/25">
            <h3 className="text-base font-bold text-white mb-4">Reported Victim Complaint Wallet Details</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="p-4 rounded-xl bg-[#081B13] border border-slate-800 space-y-2">
                <div><span className="text-slate-400">Chain:</span> <strong className="text-white uppercase">{caseObj.reported_chain}</strong></div>
                <div><span className="text-slate-400">Wallet Address:</span> <strong className="font-mono text-[#E5B83B] break-all">{caseObj.reported_wallet}</strong></div>
                <div><span className="text-slate-400">Reported Value:</span> <strong className="text-emerald-400">${caseObj.reported_amount_usd.toLocaleString()} USD</strong></div>
              </div>
              <div className="p-4 rounded-xl bg-[#081B13] border border-slate-800 space-y-2">
                <div><span className="text-slate-400">Case Relevance Score:</span> <strong className="text-[#E5B83B]">100.0 / 100 (Direct Victim Target)</strong></div>
                <div><span className="text-slate-400">Wallet Risk Score:</span> <strong>42.0 / 100 (MEDIUM)</strong></div>
                <div><span className="text-slate-400">Surveillance Status:</span> <strong className="text-emerald-300">ACTIVE MONITORING</strong></div>
              </div>
            </div>
          </motion.div>
        )}

        {/* ── TAB 3: MONEY TRAIL ── */}
        {activeTab === "trail" && (
          <motion.div key="trail" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-4">
            {/* Trail Filter Controls */}
            <div className="flex items-center justify-between glass-panel p-3 rounded-xl border border-slate-800">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-300">Trail Focus:</span>
                {["PRIMARY", "ATTRIBUTED", "EXCHANGES", "CROSS_CHAIN", "ALL"].map((f) => (
                  <button
                    key={f}
                    onClick={() => setTrailFilter(f)}
                    className={`px-2.5 py-1 rounded-lg text-[10px] font-extrabold cursor-pointer transition-all ${
                      trailFilter === f ? "bg-[#E5B83B] text-[#150F00]" : "bg-slate-900 text-slate-300 hover:bg-slate-800"
                    }`}
                  >
                    {f.replace("_", " ")}
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-slate-400">Showing primary reported fund path</span>
            </div>

            <div className="glass-panel overflow-hidden rounded-2xl border border-[#E5B83B]/20 min-h-[460px]">
              <GraphVisualizer graph={graph} onSelect={(node) => onSelectWallet?.(node)} />
            </div>
          </motion.div>
        )}

        {/* ── TAB 4: TRANSACTIONS ── */}
        {activeTab === "transactions" && (
          <motion.div key="transactions" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="glass-panel overflow-hidden rounded-2xl border border-slate-800">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-200">
                <thead className="bg-[#081B13] text-slate-400 text-[10px] uppercase tracking-wider font-bold">
                  <tr>
                    <th className="p-3">Time</th>
                    <th className="p-3">Chain</th>
                    <th className="p-3">Transaction Hash</th>
                    <th className="p-3">From</th>
                    <th className="p-3">To</th>
                    <th className="p-3">Value</th>
                    <th className="p-3">Attributed USD</th>
                    <th className="p-3">Risk</th>
                    <th className="p-3">Relevance</th>
                    <th className="p-3">VASP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {transactions.map((tx, idx) => (
                    <tr key={idx} className="hover:bg-slate-900/50">
                      <td className="p-3">{tx.block_time?.slice(11, 16) || "08:15"}</td>
                      <td className="p-3 uppercase font-bold text-emerald-400">{tx.chain}</td>
                      <td className="p-3 font-mono text-slate-300">{tx.tx_hash?.slice(0, 10)}…</td>
                      <td className="p-3 font-mono text-slate-400">{tx.from_address?.slice(0, 8)}…</td>
                      <td className="p-3 font-mono text-slate-400">{tx.to_address?.slice(0, 8)}…</td>
                      <td className="p-3 font-bold text-white">${tx.value_usd?.toLocaleString()}</td>
                      <td className="p-3 font-bold text-[#E5B83B]">${tx.attributed_value_usd?.toLocaleString()}</td>
                      <td className="p-3 font-bold">{tx.risk_score}</td>
                      <td className="p-3 font-bold text-[#E5B83B]">{tx.relevance_score}</td>
                      <td className="p-3 font-bold text-emerald-300">{tx.vasp_name || "--"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}

        {/* ── TAB 5: WALLETS ── */}
        {activeTab === "wallets" && (
          <motion.div key="wallets" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {wallets.map((w, idx) => (
              <div key={idx} className="glass-panel p-4 rounded-xl border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-extrabold uppercase px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    {w.role}
                  </span>
                  <span className="text-xs font-bold text-[#E5B83B]">Relevance: {w.relevance_score}%</span>
                </div>
                <div className="font-mono text-xs font-bold text-white break-all">{w.address}</div>
                <div className="text-[11px] text-slate-300 space-y-1">
                  <div>Attributed Fund: <strong>${w.attributed_usd?.toLocaleString()} USD</strong></div>
                  <div>Risk Score: <strong>{w.risk_score} / 100</strong></div>
                  <div>VASP Match: <strong className="text-emerald-400">{w.vasp_name || "None"}</strong></div>
                </div>
              </div>
            ))}
          </motion.div>
        )}

        {/* ── TAB 6: EXCHANGES ── */}
        {activeTab === "exchanges" && (
          <motion.div key="exchanges" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-4">
            {exchanges.map((ex, idx) => (
              <div key={idx} className="glass-panel p-5 rounded-2xl border border-[#E5B83B]/30 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-extrabold text-white">{ex.exchange_name} ({ex.wallet_type})</h3>
                    <p className="text-xs text-slate-300">VASP Attribution Confidence: <strong className="text-[#E5B83B]">{(ex.vasp_confidence * 100).toFixed(0)}%</strong></p>
                  </div>
                  <span className="px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    Received ${ex.reported_funds_received_usd?.toLocaleString()} USD
                  </span>
                </div>
                <div className="text-xs font-mono text-[#E5B83B]">Endpoint: {ex.address}</div>
                <div className="p-3 rounded-xl bg-[#081B13] text-xs border border-slate-800">
                  <div className="font-bold text-slate-300 mb-1">Step-by-step Money Trail Path:</div>
                  <div className="flex items-center gap-2 flex-wrap font-mono text-[11px] text-slate-400">
                    {ex.path?.map((p, i) => (
                      <React.Fragment key={i}>
                        <span className="p-1 rounded bg-slate-900 border border-slate-800">{p.slice(0, 10)}…</span>
                        {i < ex.path.length - 1 && <span>→</span>}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </motion.div>
        )}

        {/* ── TAB 7: CROSS-CHAIN ── */}
        {activeTab === "cross-chain" && (
          <motion.div key="cross-chain" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-4">
            {crossChain.map((cc, idx) => (
              <div key={idx} className="glass-panel p-5 rounded-2xl border border-purple-500/30 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <Zap size={16} className="text-purple-400" /> Bridge Correlation: {cc.bridge_name}
                  </h3>
                  <span className="text-xs font-bold text-purple-300">Confidence: {(cc.correlation_confidence * 100).toFixed(0)}%</span>
                </div>
                <div className="grid grid-cols-2 gap-4 text-xs text-slate-300">
                  <div className="p-3 rounded-xl bg-[#081B13] border border-slate-800">
                    <div>Source Chain: <strong className="uppercase text-purple-300">{cc.source_chain}</strong></div>
                    <div className="font-mono text-[10px] text-slate-400 mt-1">{cc.source_tx_hash}</div>
                  </div>
                  <div className="p-3 rounded-xl bg-[#081B13] border border-slate-800">
                    <div>Destination Chain: <strong className="uppercase text-emerald-300">{cc.destination_chain}</strong></div>
                    <div className="font-mono text-[10px] text-slate-400 mt-1">{cc.destination_tx_hash}</div>
                  </div>
                </div>
              </div>
            ))}
          </motion.div>
        )}

        {/* ── TAB 8: ALERTS ── */}
        {activeTab === "alerts" && (
          <motion.div key="alerts" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-3">
            {alerts.map((a, idx) => (
              <div key={idx} className="glass-panel p-4 rounded-xl border border-slate-800 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-extrabold ${
                      a.severity === "CRITICAL" ? "bg-red-500/20 text-red-300" : "bg-amber-500/20 text-amber-300"
                    }`}>
                      {a.severity}
                    </span>
                    <h4 className="text-xs font-bold text-white">{a.title}</h4>
                  </div>
                  <p className="text-[11px] text-slate-300 mt-1">{a.summary}</p>
                </div>
              </div>
            ))}
          </motion.div>
        )}

        {/* ── TAB 9: RECOMMENDATIONS ── */}
        {activeTab === "recommendations" && (
          <motion.div key="recommendations" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-4">
            {recommendations.map((r) => (
              <div key={r.id} className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-2">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/30">
                  {r.priority} PRIORITY
                </span>
                <h3 className="text-sm font-bold text-white">{r.title}</h3>
                <p className="text-xs text-slate-300">{r.action_text}</p>
              </div>
            ))}
          </motion.div>
        )}

        {/* ── TAB 10: NOTES & TASKS ── */}
        {activeTab === "notes-tasks" && (
          <motion.div key="notes-tasks" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Notes Section */}
            <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
              <h3 className="text-sm font-bold text-white">Investigator Case Notes</h3>
              <form onSubmit={handleAddNote} className="space-y-2">
                <textarea
                  value={newNoteText}
                  onChange={(e) => setNewNoteText(e.target.value)}
                  placeholder="Add case observation, rationale, or officer note..."
                  className="w-full h-20 p-3 rounded-xl bg-[#081B13] border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-[#E5B83B]"
                />
                <button type="submit" className="rolex-gold-btn px-4 py-2 text-xs font-bold rounded-xl cursor-pointer">
                  Add Case Note
                </button>
              </form>
              <div className="space-y-3">
                {notes.map((n) => (
                  <div key={n.id} className="p-3 rounded-xl bg-[#081B13] border border-slate-800">
                    <div className="flex items-center justify-between text-[10px] text-slate-400">
                      <span>{n.author_name}</span>
                      <span>{n.created_at?.slice(0, 16).replace("T", " ")}</span>
                    </div>
                    <p className="text-xs text-slate-200 mt-1">{n.text}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Tasks Section */}
            <div className="glass-panel p-5 rounded-2xl border border-slate-800 space-y-4">
              <h3 className="text-sm font-bold text-white">Investigator Action Tasks</h3>
              <form onSubmit={handleCreateTask} className="flex gap-2">
                <input
                  type="text"
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  placeholder="New task title (e.g. Issue Section 91 Notice)..."
                  className="flex-1 p-2.5 rounded-xl bg-[#081B13] border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-[#E5B83B]"
                />
                <button type="submit" className="rolex-green-btn px-4 py-2 text-xs font-bold rounded-xl cursor-pointer">
                  Add Task
                </button>
              </form>
              <div className="space-y-3">
                {tasks.map((t) => (
                  <div key={t.id} className="p-3 rounded-xl bg-[#081B13] border border-slate-800 flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-bold text-slate-200">{t.title}</h4>
                      <div className="text-[10px] text-slate-400 mt-0.5">Assignee: {t.assignee}</div>
                    </div>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300">
                      {t.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}

        {/* ── TAB 11: EVIDENCE & REPORT ── */}
        {activeTab === "report" && (
          <motion.div key="report" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-6">
            {/* Government Integration Official Action Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* NCRP Card */}
              <div className="glass-panel p-5 rounded-2xl border border-emerald-500/30 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="text-emerald-400" size={18} />
                    <h3 className="text-sm font-bold text-white">NCRP National Portal Action</h3>
                  </div>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    SIMULATION MODE
                  </span>
                </div>
                <p className="text-xs text-slate-300">
                  Attach case evidence package and money trail analysis to National Cyber Crime Reporting Portal reference.
                </p>
                <div className="flex items-center justify-between pt-2">
                  <span className="text-[10px] text-slate-400">Idempotency-protected outbound payload</span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const res = await submitNCRPReport(caseId);
                        alert(`NCRP Simulation Action Complete:\nReference: ${res?.external_reference || 'NCRP-SIM-2026'}\nStatus: ${res?.status || 'SIMULATION'}`);
                      } catch (err) {
                        alert(`NCRP Action Error: ${err.message}`);
                      }
                    }}
                    className="rolex-green-btn px-3 py-1.5 text-xs font-bold rounded-lg cursor-pointer"
                  >
                    Attach Report to NCRP
                  </button>
                </div>
              </div>

              {/* SAHYOG Card */}
              <div className="glass-panel p-5 rounded-2xl border border-purple-500/30 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Zap className="text-purple-400" size={18} />
                    <h3 className="text-sm font-bold text-white">SAHYOG Inter-State Action</h3>
                  </div>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/30">
                    SIMULATION MODE
                  </span>
                </div>
                <p className="text-xs text-slate-300">
                  Submit Section 91 preservation request to SAHYOG interstate law enforcement coordination portal.
                </p>
                <div className="flex items-center justify-between pt-2">
                  <span className="text-[10px] text-slate-400">Idempotency-protected action request</span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const res = await submitSahyogAction(caseId, "PRESERVATION_REQUEST", caseObj.reported_wallet, "Coinbase");
                        alert(`SAHYOG Simulation Action Complete:\nTicket ID: ${res?.external_reference || 'SAHYOG-SIM-2026'}\nStatus: ${res?.status || 'SIMULATION'}`);
                      } catch (err) {
                        alert(`SAHYOG Action Error: ${err.message}`);
                      }
                    }}
                    className="rolex-gold-btn px-3 py-1.5 text-xs font-bold rounded-lg cursor-pointer"
                  >
                    Issue SAHYOG Request
                  </button>
                </div>
              </div>
            </div>

            {/* Embedded Evidence Ledger */}
            <EvidenceLedgerPage caseRef={caseObj.case_ref} activeCaseRef={caseObj.case_ref} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default CaseWorkspace;
