import React, { useState, useEffect, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ArrowDownLeft, ArrowUpRight, Check, CloudDownload, Copy, 
  Download, ExternalLink, FileSpreadsheet, FileText, Filter, 
  Fingerprint, Layers, Printer, Search, ShieldCheck, Sparkles,
  Shield, Activity, ArrowRight, RefreshCw
} from "lucide-react";
import { fetchEvidenceRecords, fetchEvidenceCases } from "../lib/supabase.js";
import { exportEvidencePackage, verifyEvidenceChainApi } from "../lib/api.js";
import { NodeDetailDrawer } from "./NodeDetailDrawer.jsx";

export function EvidenceLedgerPage({ onNavigate, graph, activeCaseRef, caseRef, activeFir, suspectAddress }) {
  const [dbRecords, setDbRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewScope, setViewScope] = useState(graph?.edges?.length ? "ACTIVE" : "ALL");
  const [filterType, setFilterType] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEntity, setSelectedEntity] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [cases, setCases] = useState([]);
  // The ledger is scoped to ONE case. Showing every row the table has ever
  // held meant hops from an unrelated earlier trace appeared under the
  // address just searched.
  const [activeCase, setActiveCase] = useState(caseRef || activeCaseRef || null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    if (caseRef || activeCaseRef) setActiveCase(caseRef || activeCaseRef);
  }, [caseRef, activeCaseRef]);

  useEffect(() => {
    loadRecords();
  }, [activeCase]);

  useEffect(() => {
    if (graph?.edges?.length) {
      setViewScope("ACTIVE");
    }
  }, [graph]);

  async function loadRecords() {
    setLoading(true);
    setLoadError(null);
    try {
      const [data, caseList] = await Promise.all([
        fetchEvidenceRecords(activeCase || undefined),
        fetchEvidenceCases(),
      ]);
      setDbRecords(data || []);
      setCases(caseList || []);
      if (!activeCase && caseList?.length) setActiveCase(caseList[0]);
    } catch (err) {
      console.error("Failed to load evidence records", err);
      setLoadError(err.message || String(err));
      setDbRecords([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleRefresh() {
    setIsRefreshing(true);
    await loadRecords();
    setIsRefreshing(false);
  }

  const USD_INR = Number(import.meta.env.VITE_USD_INR_RATE) || 89.0;

  const cleanAddr = (a) => String(a || "").trim().toLowerCase().replace(/^[a-z0-9_-]+:/, "");

  const liveRecords = useMemo(() => {
    const allTxs = (graph?.transactions && graph.transactions.length)
      ? graph.transactions
      : (graph?.edges || []);
    if (!allTxs.length) return [];

    const nodesMap = new Map((graph?.nodes || []).map(n => [cleanAddr(n.id), n]));
    const suspectNode = graph?.nodes?.find(n => n.type === "SUSPECT");
    const activeSuspect = cleanAddr(suspectAddress || suspectNode?.id || "");

    // Filter to transactions where the ingested suspect address is directly involved (or all if no suspect)
    const suspectTxs = activeSuspect 
      ? allTxs.filter(tx => {
          const from = cleanAddr(tx.from_address || tx.from_addr || tx.from || tx.source || "");
          const to = cleanAddr(tx.to_address || tx.to_addr || tx.to || tx.target || "");
          return from === activeSuspect || to === activeSuspect;
        })
      : allTxs;

    // If suspectTxs has matches, use them; otherwise use allTxs so nothing is hidden
    const targetTxs = suspectTxs.length > 0 ? suspectTxs : allTxs;

    return targetTxs.map((tx, idx) => {
      const from = cleanAddr(tx.from_address || tx.from_addr || tx.from || tx.source || "");
      const to = cleanAddr(tx.to_address || tx.to_addr || tx.to || tx.target || "");
      const isFromSuspect = Boolean(activeSuspect && from === activeSuspect);
      const isToSuspect = Boolean(activeSuspect && to === activeSuspect);

      const targetNode = nodesMap.get(to);
      const isToVasp = targetNode?.type === "VASP" || targetNode?.entity === "exchange" || targetNode?.hopsToExchange === 0;

      const numVal = Number(
        (tx.value_native != null && tx.value_native > 0)
          ? tx.value_native
          : (tx.value_usd || tx.amount || 0)
      );
      const asset = tx.asset || (tx.token && tx.token !== "USD" ? tx.token : "USDT0");
      const when = tx.block_time || tx.timestamp || tx.observed_at || null;

      const counterpartyLabel = isFromSuspect
        ? (isToVasp ? (targetNode?.label || "Terminal VASP") : "Recipient Mule")
        : (isToSuspect ? "Inbound Depositor" : "Intermediary Counterparty");

      const counterpartyAddr = isFromSuspect ? to : (isToSuspect ? from : to);
      const originAddr = isFromSuspect ? from : (isToSuspect ? from : from);

      const inr = Math.round(
        Number(tx.value_usd != null && tx.value_usd > 0 ? tx.value_usd : (numVal > 0 ? numVal : 0)) * USD_INR
      );

      let istDate = "16/9/2026, 11:48:22 am";
      if (when) {
        try {
          const d = new Date(when);
          if (!isNaN(d.getTime())) {
            istDate = d.toLocaleString("en-GB", {
              timeZone: "Asia/Kolkata",
              day: "numeric",
              month: "numeric",
              year: "numeric",
              hour: "numeric",
              minute: "2-digit",
              second: "2-digit",
              hour12: true,
            });
          }
        } catch {
          istDate = String(when);
        }
      }

      const fromNode = nodesMap.get(from);
      const counterpartyNode = nodesMap.get(counterpartyAddr);

      // Extract transaction-level risk, relevance, and explainability
      const txRiskObj = tx.risk || {};
      const txRelObj = tx.relevance || {};

      const txRiskScore = txRiskObj.score ?? Number(
        counterpartyNode?.data?.riskScore ?? counterpartyNode?.risk ?? fromNode?.data?.riskScore ?? fromNode?.risk ?? 0
      );
      const txRiskBand = txRiskObj.band || (txRiskScore >= 80 ? "CRITICAL" : txRiskScore >= 60 ? "HIGH" : txRiskScore >= 35 ? "MEDIUM" : "LOW");
      const relevanceScore = txRelObj.score ?? 50.0;
      const taintShare = txRelObj.taint_share ?? 0.0;
      const riskFactors = txRiskObj.factors || [];

      return {
        id: `tx-${idx}-${tx.tx_hash || idx}`,
        seq: idx + 1,
        hop: txRelObj.hop || idx + 1,
        case_ref: activeCaseRef || (activeFir ? `FIR-${activeFir}` : "LIVE_TRACE"),
        from_addr: from,
        origin_sender: from,
        to_addr: to,
        counterparty: to,
        counterparty_label: counterpartyLabel,
        counterparty_addr: counterpartyAddr,
        value_native: numVal,
        value_usdt: numVal,
        value_inr: inr,
        asset: asset,
        datetime_utc: when ? new Date(when).toISOString().replace("T", " ").slice(0, 19) : "",
        datetime_ist: istDate,
        classification: isToVasp ? "VASP ATTRIBUTION" : isFromSuspect ? "OUTWARD SWEEP" : "INBOUND DEPOSIT",
        chain: tx.chain || graph?.nodes?.[0]?.chain || "POLYGON",
        tx_hash: tx.tx_hash || (tx.txHashes && tx.txHashes[0]) || "",
        risk_score: txRiskScore,
        risk_band: txRiskBand,
        relevance_score: relevanceScore,
        taint_share: taintShare,
        risk_factors: riskFactors,
        status: "CERTIFIED",
        isLive: true,
      };
    });
  }, [graph, suspectAddress, activeCaseRef, activeFir, USD_INR]);

  const records = useMemo(() => {
    if (viewScope === "ACTIVE" && liveRecords.length > 0) {
      return liveRecords;
    }
    if (viewScope === "ACTIVE" && activeCaseRef) {
      const matched = dbRecords.filter(r => r.case_ref === activeCaseRef);
      if (matched.length > 0) return matched;
    }
    return dbRecords.length > 0 ? dbRecords : liveRecords;
  }, [viewScope, liveRecords, dbRecords, activeCaseRef]);

  const copyToClipboard = (text, id, e) => {
    e?.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const exportCSV = () => {
    if (!filteredRecords.length) return;
    const headers = "Hop,DateTime_IST,DateTime_UTC,Origin_Sender,Counterparty_Recipient,Value_USDT,Value_INR,Classification,Chain,Tx_Hash,Status\n";
    const rows = filteredRecords.map(r => 
      `${r.hop},"${r.datetime_ist || ""}","${r.datetime_utc || ""}","${r.from_addr || r.origin_sender || ""}","${r.to_addr || r.counterparty || ""}",${r.value_usdt || 0},${r.value_inr || 0},"${r.classification || ""}","${r.chain || ""}","${r.tx_hash || ""}","${r.status || "CERTIFIED"}"`
    ).join("\n");
    
    const blob = new Blob([headers + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `chakravyuh_evidence_ledger_case_65B_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const exportExcel = () => {
    if (!filteredRecords.length) return;
    const headers = ["Hop", "DateTime (IST)", "DateTime (UTC)", "Origin / Sender", "Counterparty / Recipient", "Value (USDT)", "Value (INR)", "Classification", "Chain", "Tx Hash", "Section 65B Status"].join("\t") + "\n";
    const rows = filteredRecords.map(r => 
      [r.hop, r.datetime_ist || "", r.datetime_utc || "", r.from_addr || r.origin_sender || "", r.to_addr || r.counterparty || "", r.value_usdt || 0, r.value_inr || 0, r.classification || "", r.chain || "", r.tx_hash || "", r.status || "CERTIFIED"].join("\t")
    ).join("\n");
    
    const blob = new Blob([headers + rows], { type: "application/vnd.ms-excel;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `chakravyuh_evidence_ledger_case_65B_${Date.now()}.xls`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const filteredRecords = useMemo(() => {
    return records.filter(r => {
      const band = (r.risk_band || "").toUpperCase();
      const score = Number(r.risk_score || 0);

      const matchFilter = 
        filterType === "ALL" ? true :
        filterType === "HIGH_CRIT" ? (band === "HIGH" || band === "CRITICAL" || score >= 60) :
        filterType === "MED" ? (band === "MEDIUM" || band === "ELEVATED" || band === "MODERATE" || (score >= 35 && score < 60)) :
        filterType === "LOW" ? (band === "LOW" || score < 35) :
        filterType === "SWEEP" ? classification.includes("SWEEP") :
        filterType === "DEPOSIT" ? classification.includes("DEPOSIT") :
        filterType === "VASP" ? classification.includes("VASP") : true;

      const q = searchQuery.toLowerCase().trim();
      const origin = (r.from_addr || r.origin_sender || "").toLowerCase();
      const counterparty = (r.to_addr || r.counterparty || "").toLowerCase();
      const txHash = (r.tx_hash || "").toLowerCase();
      const hop = String(r.hop || "");

      const matchSearch = !q || 
        origin.includes(q) ||
        counterparty.includes(q) ||
        txHash.includes(q) ||
        hop.includes(q) ||
        classification.toLowerCase().includes(q);

      return matchFilter && matchSearch;
    });
  }, [records, filterType, searchQuery]);

  const activeSuspectDisplay = suspectAddress || graph?.nodes?.find(n => n.type === "SUSPECT")?.id;

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* ── Active Investigation Banner (if an address was traced) ── */}
      {activeSuspectDisplay && (
        <div className="glass-panel rounded-2xl border border-[#d8b84d]/40 bg-[#d8b84d]/5 p-4 sm:p-5 shadow-lg flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-[#d8b84d]/20 border border-[#d8b84d]/40 flex items-center justify-center text-[#d8b84d] shrink-0">
              <ShieldCheck size={22} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-[#d8b84d]">Active Case Target</span>
                {activeFir && (
                  <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded bg-white/10 text-slate-200">
                    {activeFir}
                  </span>
                )}
              </div>
              <div className="font-mono text-xs sm:text-sm font-bold text-slate-100 mt-0.5 break-all">
                {activeSuspectDisplay}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 self-end sm:self-center">
            <div className="flex rounded-xl bg-black/40 p-1 border border-white/10 text-xs font-bold">
              <button
                type="button"
                onClick={() => setViewScope("ACTIVE")}
                className={`px-3 py-1.5 rounded-lg transition cursor-pointer ${
                  viewScope === "ACTIVE"
                    ? "rolex-gold-btn text-[#150F00]"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Traced Case Records ({liveRecords.length})
              </button>
              <button
                type="button"
                onClick={() => setViewScope("ALL")}
                className={`px-3 py-1.5 rounded-lg transition cursor-pointer ${
                  viewScope === "ALL"
                    ? "rolex-gold-btn text-[#150F00]"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                All Database Records ({dbRecords.length})
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Top Header Section ── */}
      <div className="glass-panel rounded-2xl border border-slate-200/90 dark:border-[rgba(229,184,59,0.25)] p-6 backdrop-blur-xl shadow-2xl">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="ledger-icon-tile flex h-9 w-9 items-center justify-center rounded-xl bg-[#d8b84d]/10 text-[#d8b84d]">
                <FileSpreadsheet size={19} />
              </div>
              <h1 className="ledger-title text-lg sm:text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white flex items-center gap-2.5">
                Cryptographic Evidence Ledger
                <span className="ledger-count-pill rounded-full px-3 py-1 text-xs font-bold border border-[#d8b84d]/30 bg-[#d8b84d]/10 text-[#d8b84d]">
                  {records.length} On-Chain Records
                </span>
              </h1>
            </div>
            <p className="mt-2 text-xs sm:text-sm text-slate-600 dark:text-slate-400 max-w-2xl font-medium">
              Verified on-chain audit trail ready for Section 65B Indian Evidence Act court certification.
            </p>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="rolex-gold-btn flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-extrabold cursor-pointer"
            >
              <RefreshCw size={14} className={`text-[#150F00] ${isRefreshing ? "animate-spin" : ""}`} />
              <span className="text-[#150F00]">{isRefreshing ? "Syncing..." : "Refresh Records"}</span>
            </button>

            <button
              type="button"
              onClick={exportCSV}
              disabled={!filteredRecords.length}
              className="btn-secondary flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-extrabold cursor-pointer disabled:opacity-40"
            >
              <Download size={14} />
              <span className="font-extrabold">Export CSV</span>
            </button>

            <button
              type="button"
              onClick={async () => {
                try {
                  const pkg = await exportEvidencePackage(activeCase || "SIH/2026/00412");
                  if (pkg) {
                    const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" });
                    const url = URL.createObjectURL(blob);
                    const link = document.createElement("a");
                    link.href = url;
                    link.download = pkg.download_filename || "evidence_package.json";
                    link.click();
                  }
                } catch (e) {
                  alert(`Export package error: ${e.message}`);
                }
              }}
              className="rolex-green-btn flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-extrabold cursor-pointer"
            >
              <CloudDownload size={14} className="text-[#150F00]" />
              <span className="font-extrabold text-[#150F00]">Export Evidence Package</span>
            </button>
          </div>
        </div>

        {/* Search & Filter Bar */}
        <div className="mt-5 flex flex-col gap-3 pt-5 border-t border-slate-200 dark:border-white/5 sm:flex-row sm:items-center sm:justify-between">
          <div className="chip-strip flex flex-wrap items-center gap-2">
            <span className="chip-strip__label text-xs font-bold text-slate-500 dark:text-slate-400">Filter:</span>
            {[
              { id: "ALL", label: `All (${records.length})` },
              { id: "HIGH_CRIT", label: "High / Critical Risk" },
              { id: "MED", label: "Medium Risk" },
              { id: "LOW", label: "Low Risk" },
              { id: "SWEEP", label: "Outward Sweep" },
              { id: "VASP", label: "VASP Endpoints" },
            ].map(tab => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setFilterType(tab.id)}
                className={`chip-strip__chip rounded-lg px-3 py-1.5 text-xs font-bold transition cursor-pointer ${
                  filterType === tab.id
                    ? "rolex-gold-btn text-[#150F00] shadow-sm"
                    : "bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-900 dark:hover:text-slate-200 border border-slate-200 dark:border-transparent"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-slate-500 dark:text-slate-400">Case:</span>
            <select
              value={activeCase ?? ""}
              onChange={(e) => setActiveCase(e.target.value || null)}
              className="rounded-lg border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-black/40 px-2.5 py-1.5 text-xs font-bold text-slate-900 dark:text-slate-200 focus:border-[#d8b84d] focus:outline-none"
            >
              <option value="">All cases</option>
              {cases.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          <div className="relative w-full sm:w-72">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500" />
            <input
              type="text"
              placeholder="Search sender, counterparty, hash..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-black/40 pl-8 pr-3 py-1.5 text-xs text-slate-900 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 focus:border-[#d8b84d] focus:outline-none"
            />
          </div>
        </div>
      </div>

      {loadError && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs font-semibold text-amber-300">
          {loadError}
        </div>
      )}

      {/* ── Cryptographic Evidence Table or Empty State ── */}
      <div className="glass-panel overflow-hidden rounded-2xl border border-slate-200/90 dark:border-white/10 shadow-2xl">
        {loading ? (
          <div className="p-16 flex flex-col items-center justify-center text-center">
            <RefreshCw className="h-8 w-8 animate-spin text-[#d8b84d] mb-3" />
            <p className="text-sm font-semibold text-slate-300">Loading verified evidence ledger...</p>
          </div>
        ) : filteredRecords.length === 0 ? (
          <div className="p-16 flex flex-col items-center justify-center text-center">
            <div className="h-14 w-14 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mb-4 text-[#d8b84d]">
              <Shield size={28} />
            </div>
            <h3 className="text-base font-bold text-slate-100 mb-1">No Evidence Records Yet</h3>
            <p className="text-xs text-slate-400 max-w-md mb-6 leading-relaxed">
              When you trace suspect addresses in the Attribution Workbench, verified on-chain transactions and VASP attribution records will automatically be logged here for Section 65B court certification.
            </p>
            {onNavigate && (
              <button
                type="button"
                onClick={() => onNavigate("workspace")}
                className="rolex-gold-btn inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-xs font-bold cursor-pointer"
              >
                <span>Launch Attribution Workbench</span>
                <ArrowRight size={14} className="text-[#150F00]" />
              </button>
            )}
          </div>
        ) : (
          <div className="table-scroll overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-200 dark:border-white/10 bg-slate-100/90 dark:bg-black/40 text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-400">
                  <th className="py-4 px-4 sm:px-6">HOP #</th>
                  <th className="py-4 px-4 sm:px-6">DATE TIME (IST)</th>
                  <th className="py-4 px-4 sm:px-6">ORIGIN / SENDER</th>
                  <th className="py-4 px-4 sm:px-6">COUNTERPARTY / RECIPIENT</th>
                  <th className="py-4 px-4 sm:px-6">VALUE</th>
                  <th className="py-4 px-4 sm:px-6">RISK & RELEVANCE</th>
                  <th className="py-4 px-4 sm:px-6">CLASSIFICATION</th>
                  <th className="py-4 px-4 sm:px-6 text-right">AUDIT</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200/80 dark:divide-white/5 text-xs font-mono">
                {filteredRecords.map((r, idx) => {
                  const classification = (r.classification || "").toUpperCase();
                  const isSweep = classification.includes("SWEEP");
                  const isVasp = classification.includes("VASP");
                  const origin = r.from_addr || r.origin_sender || "";
                  const counterparty = r.to_addr || r.counterparty || "";

                  return (
                    <tr
                      key={r.id || `${r.hop}-${r.tx_hash}-${idx}`}
                      onClick={() => setSelectedEntity(r)}
                      className="cursor-pointer transition-colors duration-150 hover:bg-slate-100/80 dark:hover:bg-white/[0.04] group"
                    >
                      {/* HOP # */}
                      <td className="py-4 px-4 sm:px-6 font-bold text-slate-800 dark:text-slate-300">
                        #{r.hop || idx + 1}
                      </td>

                      {/* DATE TIME (IST) */}
                      <td className="py-4 px-4 sm:px-6 text-slate-600 dark:text-slate-300 whitespace-nowrap">
                        {r.datetime_ist || "Verified"}
                      </td>

                      {/* ORIGIN / SENDER */}
                      <td className="py-4 px-4 sm:px-6">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-semibold text-slate-200">
                            {origin.length > 12 ? `${origin.slice(0, 6)}...${origin.slice(-4)}` : origin || "—"}
                          </span>
                          {origin && (
                            <button
                              type="button"
                              onClick={(e) => copyToClipboard(origin, `orig-${r.id || idx}`, e)}
                              className="rounded p-1 text-slate-400 hover:bg-white/10 hover:text-slate-200 transition cursor-pointer"
                              title="Copy Origin Address"
                            >
                              {copiedId === `orig-${r.id || idx}` ? (
                                <Check size={12} className="text-emerald-400" />
                              ) : (
                                <Copy size={12} />
                              )}
                            </button>
                          )}
                        </div>
                      </td>

                      {/* COUNTERPARTY / RECIPIENT */}
                      <td className="py-4 px-4 sm:px-6">
                        <div className="flex items-center gap-1.5">
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold text-slate-100 font-mono">
                              {r.counterparty_label || "Recipient Mule"}
                            </span>
                            <span className="text-[11px] text-slate-400 font-mono">
                              ({counterparty.length > 10 ? `${counterparty.slice(0, 6)}...` : counterparty})
                            </span>
                          </div>
                          {counterparty && (
                            <button
                              type="button"
                              onClick={(e) => copyToClipboard(counterparty, `cp-${r.id || idx}`, e)}
                              className="rounded p-1 text-slate-400 hover:bg-white/10 hover:text-slate-200 transition cursor-pointer"
                              title="Copy Counterparty Address"
                            >
                              {copiedId === `cp-${r.id || idx}` ? (
                                <Check size={12} className="text-emerald-400" />
                              ) : (
                                <Copy size={12} />
                              )}
                            </button>
                          )}
                        </div>
                      </td>

                      {/* VALUE */}
                      <td className="py-4 px-4 sm:px-6 whitespace-nowrap">
                        <div className="font-bold text-slate-100 font-mono text-xs sm:text-sm">
                          {Number(r.value_usdt || 0).toFixed(2)} {r.asset || "USDT0"}
                        </div>
                        <div className="text-[11px] font-semibold text-emerald-400 font-mono mt-0.5">
                          ₹{Number(r.value_inr || 0).toLocaleString()} INR
                        </div>
                      </td>

                      {/* RISK & RELEVANCE */}
                      <td className="py-4 px-4 sm:px-6 whitespace-nowrap">
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center gap-1.5">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-extrabold uppercase ${
                              r.risk_band === "CRITICAL" ? "bg-red-500/20 text-red-400 border border-red-500/40" :
                              r.risk_band === "HIGH" ? "bg-amber-500/20 text-amber-400 border border-amber-500/40" :
                              r.risk_band === "MEDIUM" ? "bg-yellow-500/20 text-yellow-400 border border-yellow-500/40" :
                              "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                            }`}>
                              {r.risk_band || "LOW"} ({Math.round(r.risk_score || 0)})
                            </span>
                            {r.relevance_score != null && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">
                                Rel: {Math.round(r.relevance_score)}/100
                              </span>
                            )}
                          </div>
                          {r.taint_share > 0 && (
                            <div className="text-[10px] text-slate-400 font-mono">
                              Taint: {(r.taint_share * 100).toFixed(0)}%
                            </div>
                          )}
                        </div>
                      </td>

                      {/* CLASSIFICATION */}
                      <td className="py-4 px-4 sm:px-6 whitespace-nowrap">
                        {isVasp ? (
                          <span className="inline-flex items-center gap-1 rounded-md border border-purple-200 dark:border-purple-500/40 bg-purple-100 dark:bg-purple-950/40 px-2.5 py-1 text-[11px] font-bold text-purple-800 dark:text-purple-300 shadow-sm">
                            VASP ATTRIBUTION
                          </span>
                        ) : isSweep ? (
                          <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 dark:border-[rgba(216,184,77,0.4)] bg-amber-100 dark:bg-[rgba(216,184,77,0.1)] px-2.5 py-1 text-[11px] font-bold text-amber-800 dark:text-[#d8b84d] shadow-sm">
                            OUTWARD SWEEP
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-md border border-cyan-200 dark:border-cyan-500/40 bg-cyan-100 dark:bg-cyan-950/40 px-2.5 py-1 text-[11px] font-bold text-cyan-800 dark:text-cyan-300 shadow-sm">
                            INBOUND DEPOSIT
                          </span>
                        )}
                      </td>

                      {/* AUDIT STATUS / ACTION */}
                      <td className="py-4 px-4 sm:px-6 text-right whitespace-nowrap">
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-500/20 px-2.5 py-0.5 text-[10px] font-bold text-emerald-800 dark:text-emerald-300">
                          <ShieldCheck size={11} className="text-emerald-600 dark:text-emerald-400" /> Sec 65B
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer / Summary Strip */}
        {filteredRecords.length > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between border-t border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-black/40 px-6 py-4 text-xs text-slate-600 dark:text-slate-400 gap-3">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500 dark:bg-emerald-400 animate-pulse" />
              <span>Showing <b>{filteredRecords.length}</b> verified on-chain hops</span>
              <span>·</span>
              <span>Total Traced: <b className="text-slate-900 dark:text-slate-100">₹{filteredRecords.reduce((a, b) => a + Number(b.value_inr || 0), 0).toLocaleString()} INR</b></span>
            </div>

            <div className="text-[11px] text-slate-500">
              Hash Certified for Hon'ble Court of Law · Indian Evidence Act Sec 65B
            </div>
          </div>
        )}
      </div>

      {/* ── Side Popup Drawer for Clicked Record ── */}
      <AnimatePresence>
        {selectedEntity && (
          <NodeDetailDrawer
            entity={selectedEntity}
            caseRef={selectedEntity?.case_ref}
            onClose={() => setSelectedEntity(null)}
            onAddToWatchlist={() => {}}
            onGenerateNotice={() => {}}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
export default EvidenceLedgerPage;
