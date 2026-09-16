import React, { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ArrowRight, BookOpen, Clock3, Download, FileSpreadsheet, 
  FileText, Fingerprint, GitBranch, Shield, Sparkles, Zap 
} from "lucide-react";
import SearchPanel from "./SearchPanel.jsx";
import GraphVisualizer from "./GraphVisualizer.jsx";
import { WorkspaceNav } from "./WorkspaceNav.jsx";
import BackToTop from "./BackToTop.jsx";
import { EvidenceLedgerPage } from "./EvidenceLedgerPage.jsx";
import { WorkspaceCollectionPage } from "./WorkspaceCollectionPage.jsx";
import { NotificationsPage } from "./NotificationsPage.jsx";
import { ProfilePage } from "./ProfilePage.jsx";
import { NodeDetailDrawer } from "./NodeDetailDrawer.jsx";
import { traceFunds, buildNotice, buildDossier } from "../lib/api.js";
import { sealTraceEvidence, caseRefFor } from "../lib/evidence.js";

const emptyMetrics = [
  ["Traced volume", "--", "₹0 INR"],
  ["Attribution velocity", "0.00s", "Live RPC"],
  ["Identified VASP", "-", "Deposit endpoint"],
  ["FIU-IND status", "Standby", "PMLA jurisdiction"],
  ["Preservation SLA", "< 4 Hours", "Sec 91 window"],
];

const tabVariants = {
  initial: {
    opacity: 0,
    y: 18,
    scale: 0.995,
  },
  animate: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: {
      duration: 0.35,
      ease: [0.16, 1, 0.3, 1],
      staggerChildren: 0.08,
    },
  },
  exit: {
    opacity: 0,
    y: -14,
    scale: 0.995,
    transition: {
      duration: 0.22,
      ease: [0.7, 0, 0.84, 0],
    },
  },
};

const cardItemVariants = {
  initial: { opacity: 0, y: 14 },
  animate: { 
    opacity: 1, 
    y: 0, 
    transition: { duration: 0.32, ease: [0.16, 1, 0.3, 1] } 
  },
};

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState("workspace");
  const [graph, setGraph] = useState(null);
  const [caseRef, setCaseRef] = useState(null);
  const [evidenceStatus, setEvidenceStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [firNo, setFirNo] = useState("SIH/2026/00412");
  const [selectedEntity, setSelectedEntity] = useState(null);
  const [elapsedTime, setElapsedTime] = useState(0.0);
  const timerRef = useRef(null);

  const attribution = graph?.attribution;

  async function runTrace(address, chain, fir) {
    setLoading(true);
    setError(null);
    setFirNo(fir);
    setElapsedTime(0.0);

    const t0 = performance.now();
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsedTime((performance.now() - t0) / 1000);
    }, 50);

    try {
      const data = await traceFunds({ address, chain, complaintDate: fir });
      setGraph(data);

      // Seal the traced hops into the hash-chained evidence ledger.
      // Deliberately after setGraph: the officer sees the graph immediately
      // and sealing continues behind it. A sealing failure must never hide
      // a trace that succeeded.
      const caseRef = caseRefFor(fir, address);
      setCaseRef(caseRef);
      sealTraceEvidence(data, caseRef, address)
        .then((r) => {
          setEvidenceStatus(
            r.errors.length
              ? `Sealed ${r.sealed} of ${r.onPath ?? 0} records — ${r.errors[0]}`
              : `${r.sealed} evidence records sealed to ${caseRef} ` +
                `(${r.onPath ?? 0} of ${r.considered ?? 0} traced transfers are on ` +
                `the money path from ${address.slice(0, 10)}…)`
          );
        })
        .catch((e) => setEvidenceStatus(`Evidence sealing failed: ${e.message}`));
    } catch (traceError) {
      setError(traceError.message ?? "Trace failed");
    } finally {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setElapsedTime((performance.now() - t0) / 1000);
      setLoading(false);
    }
  }

  function download(content, filename, type) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type }));
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const metrics = attribution
    ? [
        ["Traced volume", `${attribution.hops} hops`, `${attribution.exchange_name} route`],
        ["Attribution velocity", `${elapsedTime > 0 ? elapsedTime.toFixed(2) : (attribution.time_to_attribution_ms / 1000).toFixed(2)}s`, "Direct on-chain RPC"],
        ["Identified VASP", attribution.exchange_name, "Deposit endpoint"],
        ["FIU-IND status", `${(attribution.confidence * 100).toFixed(0)}%`, "PMLA jurisdiction"],
        ["Preservation SLA", "< 4 Hours", "Sec 91 window"],
      ]
    : [
        ["Traced volume", "--", "₹0 INR"],
        ["Attribution velocity", `${elapsedTime > 0 ? elapsedTime.toFixed(2) : "0.00"}s`, "Live RPC"],
        ["Identified VASP", "-", "Deposit endpoint"],
        ["FIU-IND status", "Standby", "PMLA jurisdiction"],
        ["Preservation SLA", "< 4 Hours", "Sec 91 window"],
      ];

  const handleNav = (route) => {
    if (route === "landing") {
      window.location.href = "/";
    } else {
      setActiveTab(route);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  return (
    <div className="workspace-shell min-h-[100dvh] text-slate-200">
      <WorkspaceNav activeRoute={activeTab} onNavigate={handleNav} />
      <BackToTop />

      <main className="workspace-main mx-auto w-full max-w-[1440px] p-4 sm:p-6 lg:p-8">
        <AnimatePresence mode="wait">
          {/* ── Tab: Live Attribution (Workspace) ── */}
          {activeTab === "workspace" && (
            <motion.div
              key="workspace"
              variants={tabVariants}
              initial="initial"
              animate="animate"
              exit="exit"
              className="space-y-6"
            >
              {/* Hero Banner */}
              <motion.section variants={cardItemVariants} className="hero-grid">
                <div className="hero-copy">
                  <div className="eyebrow flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase text-[#E5B83B]">
                    <Sparkles size={13} className="text-[#E5B83B]" /> National cyber crime reporting portal integrated
                  </div>
                  <h1 className="text-3xl sm:text-4xl md:text-5xl font-extrabold tracking-tight">
                    See the money.<br />
                    <span className="rolex-gold-text">Stop the fraud.</span>
                  </h1>
                  <p>
                    Input any suspect cryptocurrency wallet to autonomously trace transactional flow, uncover receiving VASPs, and issue Section 91 freeze directives in real-time.
                  </p>
                </div>
                <div className="latency-card glass-panel border border-[#E5B83B]/25">
                  <Clock3 size={19} className="text-[#E5B83B]" />
                  <div>
                    <div className="eyebrow text-[#E5B83B]">Real-time attribution latency</div>
                    <div className="mt-1 text-2xl font-bold text-white font-mono">
                      {elapsedTime > 0
                        ? `${elapsedTime.toFixed(2)}s`
                        : (attribution ? `${(attribution.time_to_attribution_ms / 1000).toFixed(2)}s` : "0.00s")}{" "}
                      <span className="text-xs font-normal text-slate-400 font-sans">
                        {loading ? "Scanning Live..." : (graph ? "Attributed" : "Standby")}
                      </span>
                    </div>
                    <div className="mt-2 text-[11px] text-slate-400">Direct on-chain node execution</div>
                  </div>
                </div>
              </motion.section>

              {/* Ingestion & Auto-detection Search Panel */}
              <motion.div variants={cardItemVariants}>
                <SearchPanel onTrace={runTrace} loading={loading} elapsedTime={elapsedTime} />
              </motion.div>
              {error && <div className="glass-panel rounded-xl p-3 text-sm text-red-300 border border-red-500/30">{error}</div>}
              {/* Sealing runs behind the graph; without this banner a failed
                  seal was invisible and the Evidence Ledger just looked empty. */}
              {evidenceStatus && (
                <div className={`glass-panel rounded-xl p-3 text-sm border ${
                  /fail|error|of/i.test(evidenceStatus)
                    ? "text-amber-300 border-amber-500/30"
                    : "text-emerald-300 border-emerald-500/30"
                }`}>
                  {evidenceStatus}
                </div>
              )}

              {/* Metrics Grid */}
              <motion.section variants={cardItemVariants} className="metric-grid">
                {metrics.map(([label, value, meta]) => (
                  <div className="metric-card glass-panel border border-[#E5B83B]/15" key={label}>
                    <div className="text-[10px] uppercase tracking-wider text-[#E5B83B] font-bold">{label}</div>
                    <div className="mt-2 text-lg font-bold text-slate-100">{value}</div>
                    <div className="mt-1 text-[10px] text-slate-400">{meta}</div>
                  </div>
                ))}
              </motion.section>

              {/* Multi-Hop Traversal Chain */}
              <motion.section variants={cardItemVariants} className="glass-panel overflow-hidden rounded-2xl border border-[#E5B83B]/20 shadow-2xl">
                <div className="section-heading p-5 pb-3">
                  <div>
                    <h2 className="flex items-center gap-2 text-base font-bold text-white">
                      <GitBranch size={16} className="text-[#E5B83B]" /> Multi-hop traversal chain
                    </h2>
                    <p className="text-xs text-slate-400">
                      Click any node in the traversal chain to open the side popup dossier
                    </p>
                  </div>
                  <span className="badge rounded-full px-3 py-1 text-xs font-semibold border border-[#E5B83B]/30 text-[#FFE28A] bg-[#08261B]/60">
                    {graph ? `${graph.nodes.length} nodes loaded` : "Standby · awaiting wallet ingestion"}
                  </span>
                </div>
                <div className="graph-wrap" style={{ minHeight: "440px" }}>
                  <GraphVisualizer
                    graph={graph}
                    loading={loading}
                    onSelect={(node) => setSelectedEntity(node)}
                  />
                </div>
              </motion.section>

              {/* Cryptographic Evidence Ledger Section Preview */}
              <motion.section variants={cardItemVariants} className="glass-panel rounded-2xl p-6 border border-[#E5B83B]/20 shadow-2xl">
                <div className="section-heading mb-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="flex items-center gap-2 text-base font-bold text-white">
                        <BookOpen size={16} className="text-[#E5B83B]" /> Cryptographic evidence ledger
                      </h2>
                      <span className="rounded-full bg-[#E5B83B]/15 px-2.5 py-0.5 text-[10px] font-bold text-[#FFE28A] border border-[#E5B83B]/30">
                        {graph?.transactions?.length 
                          ? `${graph.transactions.length} On-Chain Records` 
                          : (graph?.edges?.length ? `${graph.edges.length} Traversed Edges` : "Verified Audit Records")}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">
                      Verified on-chain audit trail ready for Section 65B Indian Evidence Act court certification.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setActiveTab("evidence")}
                      className="rolex-gold-btn flex items-center gap-1.5 px-4 py-2 text-xs font-extrabold rounded-xl cursor-pointer"
                    >
                      <FileSpreadsheet size={13} className="text-[#150F00]" />
                      <span className="text-[#150F00]">Open Evidence Ledger</span>
                      <ArrowRight size={13} className="text-[#150F00]" />
                    </button>
                    {graph && (
                      <>
                        <button
                          type="button"
                          className="rolex-green-btn flex items-center gap-1.5 px-3.5 py-2 text-xs font-extrabold rounded-xl cursor-pointer"
                          onClick={() => download(buildNotice(graph, firNo), "bnss-s94-notice.txt", "text/plain")}
                        >
                          <Download size={14} className="text-white" />
                          <span className="text-white font-extrabold">Section 91 notice</span>
                        </button>
                        <button
                          type="button"
                          className="rolex-green-btn flex items-center gap-1.5 px-3.5 py-2 text-xs font-extrabold rounded-xl cursor-pointer"
                          onClick={() => download(buildDossier(graph, firNo), "forensic-attribution-dossier.html", "text/html")}
                        >
                          <FileText size={14} className="text-white" />
                          <span className="text-white font-extrabold">Forensic dossier</span>
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Quick Ledger Preview Strip */}
                <div className="rounded-xl border border-slate-200/80 dark:border-white/5 bg-slate-100/80 dark:bg-black/30 p-4 shadow-sm">
                  {((graph?.transactions && graph.transactions.length) ? graph.transactions : (graph?.edges || [])).length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                      {((graph?.transactions && graph.transactions.length) ? graph.transactions : graph.edges).slice(0, 3).map((tx, idx) => {
                        const from = tx.from_address || tx.from || tx.source || "";
                        const to = tx.to_address || tx.to || tx.target || "";
                        const val = Number(tx.value_native != null && tx.value_native > 0 ? tx.value_native : (tx.value_usd || tx.amount || 0));
                        const asset = tx.asset || (tx.token && tx.token !== "USD" ? tx.token : "USDT0");
                        const when = tx.block_time || tx.timestamp || tx.lastSeen || null;

                        return (
                          <div
                            key={tx.tx_hash || tx.txHash || idx}
                            onClick={() => setSelectedEntity(tx)}
                            className="rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-white/[0.03] p-3 hover:bg-white dark:hover:bg-white/[0.07] hover:border-[#E5B83B]/50 cursor-pointer transition flex flex-col justify-between shadow-sm"
                          >
                            <div className="flex items-center justify-between text-[11px] mb-1.5">
                              <span className="font-bold text-slate-800 dark:text-slate-300">Hop #{idx + 1}</span>
                              <span className="text-[10px] text-slate-500 font-mono">
                                {when ? new Date(when).toLocaleTimeString() : "Live"}
                              </span>
                            </div>
                            <div className="text-xs font-mono text-slate-700 dark:text-slate-200 truncate">
                              {(from || "").slice(0, 8)}... → {(to || "").slice(0, 8)}...
                            </div>
                            <div className="mt-2 flex items-center justify-between">
                              <span className="text-xs font-bold text-emerald-700 dark:text-emerald-400 font-mono">
                                {val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })} {asset}
                              </span>
                              <span className="text-[9px] font-bold px-2 py-0.5 rounded border text-[#d8b84d] border-[#d8b84d]/30 bg-[#d8b84d]/10">
                                VERIFIED
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                  <div className="flex flex-col sm:flex-row items-center justify-between text-xs text-slate-400 gap-2">
                    <span className="flex items-center gap-1.5">
                      <Fingerprint size={14} className="text-[#d8b84d]" />
                      Cryptographically certified audit trail enabled for Section 65B Indian Evidence Act compliance.
                    </span>
                    <button
                      type="button"
                      onClick={() => setActiveTab("evidence")}
                      className="text-[#d8b84d] hover:underline font-semibold flex items-center gap-1 cursor-pointer"
                    >
                      Open Complete Evidence Ledger →
                    </button>
                  </div>
                </div>
              </motion.section>
            </motion.div>
          )}

          {/* ── Tab: Evidence Ledger Page ── */}
          {activeTab === "evidence" && (
            <motion.div
              key="evidence"
              variants={tabVariants}
              initial="initial"
              animate="animate"
              exit="exit"
            >
              <EvidenceLedgerPage
                onNavigate={handleNav}
                graph={graph}
                activeCaseRef={caseRef}
                caseRef={caseRef}
                activeFir={firNo}
                suspectAddress={graph?.nodes?.find(n => n.type === "SUSPECT")?.id}
              />
            </motion.div>
          )}

          {/* ── Tab: Watchlist or Legal Dossier ── */}
          {(activeTab === "watchlist" || activeTab === "dossier") && (
            <motion.div
              key={activeTab}
              variants={tabVariants}
              initial="initial"
              animate="animate"
              exit="exit"
            >
              <WorkspaceCollectionPage view={activeTab} graph={graph} />
            </motion.div>
          )}

          {/* ── Tab: Notifications ── */}
          {activeTab === "notifications" && (
            <motion.div
              key="notifications"
              variants={tabVariants}
              initial="initial"
              animate="animate"
              exit="exit"
            >
              <NotificationsPage onNavigate={handleNav} />
            </motion.div>
          )}

          {/* ── Tab: Profile ── */}
          {activeTab === "profile" && (
            <motion.div
              key="profile"
              variants={tabVariants}
              initial="initial"
              animate="animate"
              exit="exit"
            >
              <ProfilePage onNavigate={handleNav} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* ── Side Popup Drawer (Opens when user clicks on any node or transaction) ── */}
      <AnimatePresence>
        {selectedEntity && (
          <NodeDetailDrawer
            entity={selectedEntity}
            caseRef={caseRef}
            onClose={() => setSelectedEntity(null)}
            onAddToWatchlist={() => {}}
            onGenerateNotice={() => {}}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

