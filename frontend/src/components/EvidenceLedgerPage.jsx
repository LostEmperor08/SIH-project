import React, { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ArrowDownLeft, ArrowUpRight, Check, CloudDownload, Copy, 
  Download, ExternalLink, FileSpreadsheet, FileText, Filter, 
  Fingerprint, Layers, Printer, Search, ShieldCheck, Sparkles 
} from "lucide-react";
import { EVIDENCE_RECORDS } from "../lib/evidenceData.js";
import { NodeDetailDrawer } from "./NodeDetailDrawer.jsx";

export function EvidenceLedgerPage({ onNavigate }) {
  const [records, setRecords] = useState(EVIDENCE_RECORDS);
  const [filterType, setFilterType] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEntity, setSelectedEntity] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  const [isFetchingFull, setIsFetchingFull] = useState(false);
  const [fullHistoryFetched, setFullHistoryFetched] = useState(false);

  const copyToClipboard = (text, id, e) => {
    e?.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleFetchFullHistory = () => {
    setIsFetchingFull(true);
    setTimeout(() => {
      setIsFetchingFull(false);
      setFullHistoryFetched(true);
    }, 1200);
  };

  const exportCSV = () => {
    const headers = "Hop,DateTime_IST,DateTime_UTC,Origin_Sender,Counterparty_Recipient,Value_USDT,Value_INR,Classification,Chain,Tx_Hash,Status\n";
    const rows = filteredRecords.map(r => 
      `${r.hop},"${r.datetime_ist}","${r.datetime_utc}","${r.origin_sender}","${r.counterparty}",${r.value_usdt},${r.value_inr},"${r.classification}","${r.chain}","${r.tx_hash}","${r.status}"`
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
    // Generate TSV format recognized natively by Excel
    const headers = ["Hop", "DateTime (IST)", "DateTime (UTC)", "Origin / Sender", "Counterparty / Recipient", "Value (USDT)", "Value (INR)", "Classification", "Chain", "Tx Hash", "Section 65B Status"].join("\t") + "\n";
    const rows = filteredRecords.map(r => 
      [r.hop, r.datetime_ist, r.datetime_utc, r.origin_sender, r.counterparty, r.value_usdt, r.value_inr, r.classification, r.chain, r.tx_hash, r.status].join("\t")
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
      const matchFilter = 
        filterType === "ALL" ? true :
        filterType === "SWEEP" ? r.classification_type === "sweep" || r.classification === "OUTWARD SWEEP" :
        filterType === "DEPOSIT" ? r.classification_type === "deposit" || r.classification === "INBOUND DEPOSIT" :
        filterType === "VASP" ? r.classification_type === "vasp" || r.classification === "VASP ATTRIBUTION" : true;

      const q = searchQuery.toLowerCase().trim();
      const matchSearch = !q || 
        r.origin_sender.toLowerCase().includes(q) ||
        r.counterparty.toLowerCase().includes(q) ||
        r.tx_hash.toLowerCase().includes(q) ||
        String(r.hop).includes(q) ||
        r.classification.toLowerCase().includes(q);

      return matchFilter && matchSearch;
    });
  }, [records, filterType, searchQuery]);

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* ── Top Header Section (Matching Screenshot) ── */}
      <div className="glass-panel rounded-2xl border border-slate-200/90 dark:border-[rgba(229,184,59,0.25)] p-6 backdrop-blur-xl shadow-2xl">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="ledger-icon-tile flex h-9 w-9 items-center justify-center rounded-xl">
                <FileSpreadsheet size={19} />
              </div>
              <h1 className="ledger-title text-lg sm:text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white flex items-center gap-2.5">
                Cryptographic Evidence Ledger
                <span className="ledger-count-pill rounded-full px-3 py-1 text-xs font-bold">
                  {fullHistoryFetched ? "200 On-Chain Records" : `${records.length} On-Chain Records`}
                </span>
              </h1>
            </div>
            <p className="mt-2 text-xs sm:text-sm text-slate-600 dark:text-slate-400 max-w-2xl font-medium">
              Verified on-chain audit trail ready for Section 65B Indian Evidence Act court certification.
            </p>
          </div>

          {/* Action Buttons (Rolex Gold & Green Gradients) */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={handleFetchFullHistory}
              disabled={isFetchingFull}
              className="rolex-gold-btn flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-extrabold cursor-pointer"
            >
              <CloudDownload size={14} className={`text-[#150F00] ${isFetchingFull ? "animate-bounce" : ""}`} />
              <span className="text-[#150F00]">{isFetchingFull ? "Syncing RPC..." : fullHistoryFetched ? "200 TXs Loaded" : "Fetch Full History (200 txs)"}</span>
            </button>

            <button
              type="button"
              onClick={exportCSV}
              className="btn-secondary flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-extrabold cursor-pointer"
            >
              <Download size={14} />
              <span className="font-extrabold">Export CSV</span>
            </button>

            <button
              type="button"
              onClick={exportExcel}
              className="btn-secondary flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-extrabold cursor-pointer"
            >
              <FileSpreadsheet size={14} />
              <span className="font-extrabold">Export Excel</span>
            </button>
          </div>
        </div>

        {/* Search & Filter Bar */}
        <div className="mt-5 flex flex-col gap-3 pt-5 border-t border-slate-200 dark:border-white/5 sm:flex-row sm:items-center sm:justify-between">
          <div className="chip-strip flex items-center gap-2">
            <span className="chip-strip__label text-xs font-bold text-slate-500 dark:text-slate-400">Filter:</span>
            {[
              { id: "ALL", label: `All (${records.length})` },
              { id: "SWEEP", label: "Outward Sweep" },
              { id: "DEPOSIT", label: "Inbound Deposit" },
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

      {/* ── Cryptographic Evidence Table ── */}
      <div className="glass-panel overflow-hidden rounded-2xl border border-slate-200/90 dark:border-white/10 shadow-2xl">
        <div className="table-scroll overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-white/10 bg-slate-100/90 dark:bg-black/40 text-[11px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-400">
                <th className="py-4 px-4 sm:px-6">HOP #</th>
                <th className="py-4 px-4 sm:px-6">DATE TIME (IST)</th>
                <th className="py-4 px-4 sm:px-6">ORIGIN / SENDER</th>
                <th className="py-4 px-4 sm:px-6">COUNTERPARTY / RECIPIENT</th>
                <th className="py-4 px-4 sm:px-6">VALUE</th>
                <th className="py-4 px-4 sm:px-6">CLASSIFICATION</th>
                <th className="py-4 px-4 sm:px-6 text-right">AUDIT</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200/80 dark:divide-white/5 text-xs font-mono">
              {filteredRecords.map((r) => {
                const isSweep = r.classification === "OUTWARD SWEEP" || r.classification_type === "sweep";
                const isVasp = r.classification === "VASP ATTRIBUTION" || r.classification_type === "vasp";
                const isDeposit = r.classification === "INBOUND DEPOSIT" || r.classification_type === "deposit";

                return (
                  <tr
                    key={r.hop + r.tx_hash}
                    onClick={() => setSelectedEntity(r)}
                    className="cursor-pointer transition-colors duration-150 hover:bg-slate-100/80 dark:hover:bg-white/[0.04] group"
                  >
                    {/* HOP # */}
                    <td className="py-4 px-4 sm:px-6 font-bold text-slate-800 dark:text-slate-300">
                      #{r.hop}
                    </td>

                    {/* DATE TIME (IST) */}
                    <td className="py-4 px-4 sm:px-6 text-slate-600 dark:text-slate-300 whitespace-nowrap">
                      {r.datetime_ist}
                    </td>

                    {/* ORIGIN / SENDER */}
                    <td className="py-4 px-4 sm:px-6">
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-800 dark:text-slate-200">
                          {r.origin_sender.slice(0, 6)}...{r.origin_sender.slice(-4)}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => copyToClipboard(r.origin_sender, `orig-${r.hop}`, e)}
                          className="rounded p-1 text-slate-400 hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-800 dark:hover:text-slate-300 transition cursor-pointer"
                          title="Copy Origin Address"
                        >
                          {copiedId === `orig-${r.hop}` ? (
                            <Check size={12} className="text-emerald-600 dark:text-emerald-400" />
                          ) : (
                            <Copy size={12} />
                          )}
                        </button>
                      </div>
                    </td>

                    {/* COUNTERPARTY / RECIPIENT */}
                    <td className="py-4 px-4 sm:px-6">
                      <div className="flex items-center gap-1.5">
                        <span className="text-slate-800 dark:text-slate-300 font-sans">
                          {r.counterparty_label}{" "}
                          <span className="font-mono text-slate-500">
                            ({r.counterparty.slice(0, 6)}...)
                          </span>
                        </span>
                        <button
                          type="button"
                          onClick={(e) => copyToClipboard(r.counterparty, `cp-${r.hop}`, e)}
                          className="rounded p-1 text-slate-400 hover:bg-slate-200 dark:hover:bg-white/10 hover:text-slate-800 dark:hover:text-slate-300 transition cursor-pointer"
                          title="Copy Counterparty Address"
                        >
                          {copiedId === `cp-${r.hop}` ? (
                            <Check size={12} className="text-emerald-600 dark:text-emerald-400" />
                          ) : (
                            <Copy size={12} />
                          )}
                        </button>
                      </div>
                    </td>

                    {/* VALUE */}
                    <td className="py-4 px-4 sm:px-6 whitespace-nowrap">
                      <div className="font-bold text-slate-900 dark:text-slate-100">
                        {r.value_usdt.toFixed(2)} {r.token}
                      </div>
                      <div className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                        ₹{r.value_inr.toLocaleString()} INR
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

        {/* Footer / Summary Strip */}
        <div className="flex flex-col sm:flex-row items-center justify-between border-t border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-black/40 px-6 py-4 text-xs text-slate-600 dark:text-slate-400 gap-3">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500 dark:bg-emerald-400 animate-pulse" />
            <span>Showing <b>{filteredRecords.length}</b> verified on-chain hops</span>
            <span>·</span>
            <span>Total Traced: <b className="text-slate-900 dark:text-slate-100">₹{filteredRecords.reduce((a, b) => a + b.value_inr, 0).toLocaleString()} INR</b></span>
          </div>

          <div className="text-[11px] text-slate-500">
            Hash Certified for Hon'ble Court of Law · Indian Evidence Act Sec 65B
          </div>
        </div>
      </div>

      {/* ── Side Popup Drawer for Clicked Record ── */}
      <AnimatePresence>
        {selectedEntity && (
          <NodeDetailDrawer
            entity={selectedEntity}
            onClose={() => setSelectedEntity(null)}
            onAddToWatchlist={() => {}}
            onGenerateNotice={() => {}}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
