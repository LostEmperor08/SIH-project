import React, { useState, useEffect } from "react";
import { Activity, Eye, Loader2, Search, Sparkles, Zap, CheckCircle2 } from "lucide-react";
import Compose from "./ui/Compose.jsx";

const CHAINS = [
  { id: "Polygon PoS (USDT)", label: "Polygon PoS (USDT)", tag: "POLYGON", color: "#8247e5" },
  { id: "Ethereum (ERC-20)", label: "Ethereum (ERC-20)", tag: "ETH", color: "#627eea" },
  { id: "Tron (TRC-20)", label: "Tron (TRC-20)", tag: "TRON", color: "#ff0013" },
  { id: "Bitcoin (BTC)", label: "Bitcoin (BTC)", tag: "BTC", color: "#f7931a" },
  { id: "Crime ring convergence", label: "Crime ring convergence", tag: "AI CONVERGENCE", color: "#d8b84d" },
];



function detectChainFromAddress(addr) {
  if (!addr) return null;
  const clean = addr.trim();
  
  if (clean.toLowerCase().includes("crime") || clean.toLowerCase().includes("ring") || clean.toLowerCase().includes("mule") || clean.toLowerCase().includes("cluster")) {
    return "Crime ring convergence";
  }
  if (clean.startsWith("T") || clean.startsWith("t") || clean.toLowerCase().includes("tron")) {
    return "Tron (TRC-20)";
  }
  if (clean.startsWith("bc1") || clean.startsWith("1") || clean.startsWith("3") || clean.toLowerCase().includes("btc")) {
    return "Bitcoin (BTC)";
  }
  if (clean.startsWith("0x") || clean.startsWith("0X")) {
    // If contains poly or 0xe6d / matic
    if (clean.toLowerCase().includes("poly") || clean.toLowerCase().startsWith("0xe6d")) {
      return "Polygon PoS (USDT)";
    }
    return "Ethereum (ERC-20)";
  }
  return null;
}

export default function SearchPanel({ onTrace, loading, elapsedTime = 0 }) {
  const [address, setAddress] = useState("TX7sK...victim");
  const [chain, setChain] = useState("Tron (TRC-20)");
  const [firNo, setFirNo] = useState("SIH/2026/00412");
  const [hops, setHops] = useState(2);
  const [autoDetectedChain, setAutoDetectedChain] = useState("Tron (TRC-20)");

  // Real-time auto-detection when address changes
  const handleAddressChange = (newAddress) => {
    setAddress(newAddress);
    const detected = detectChainFromAddress(newAddress);
    if (detected) {
      setChain(detected);
      setAutoDetectedChain(detected);
    }
  };

  useEffect(() => {
    const detected = detectChainFromAddress(address);
    if (detected) {
      setChain(detected);
      setAutoDetectedChain(detected);
    }
  }, []);

  const HOP_OPTIONS = [
    { value: 0, label: "0 Hops (Ingested Wallet Only)", desc: "Strictly fetch direct transactions" },
    { value: 1, label: "1 Hop (Direct Counterparties)", desc: "Include immediate senders/receivers" },
    { value: 2, label: "2 Hops (Default)", desc: "Expand to 2nd-degree sub-network" },
    { value: 3, label: "3 Hops (Deep Trace)", desc: "Full multi-hop graph expansion" },
  ];

  return (
    <div className="glass-panel rounded-2xl p-5 border border-white/10 shadow-2xl relative overflow-hidden">
      {/* Top Header */}
      <div className="mb-4 flex items-start justify-between">
        <div>
          <div className="mb-1.5 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#d8b84d]">
            <Activity size={13} className="text-[#d8b84d]" /> Live investigation ingestion
          </div>
          <h2 className="text-lg font-bold text-slate-100">Ingest suspect wallet</h2>
        </div>
        <div className="flex items-center gap-2">
          {loading && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/50 bg-amber-950/80 px-2.5 py-1 text-[11px] font-mono font-bold text-amber-300 animate-pulse">
              <Zap size={12} className="text-amber-400" /> {elapsedTime.toFixed(2)}s
            </span>
          )}
          {autoDetectedChain && !loading && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d8b84d]/40 bg-[#d8b84d]/10 px-2.5 py-1 text-[10px] font-bold text-[#d8b84d]">
              <Zap size={11} /> Auto-detected: {autoDetectedChain}
            </span>
          )}
          <span className="status-dot rounded-full px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
            Node synced
          </span>
        </div>
      </div>

      {/* Network / Chain Option Chips Above Input (With Real-time Highlight) */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2 text-[11px] text-slate-400">
          <span>Target Network / Chain Heuristics</span>
          <span className="text-[10px] text-slate-500">Auto-matches address format</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {CHAINS.map((item) => {
            const isSelected = chain === item.id;
            const isAutoMatch = autoDetectedChain === item.id;

            return (
              <button
                type="button"
                key={item.id}
                onClick={() => {
                  setChain(item.id);
                  setAutoDetectedChain(item.id);
                }}
                className={`relative rounded-xl px-3 py-2 text-xs font-semibold transition-all duration-200 flex items-center gap-2 cursor-pointer ${
                  isSelected
                    ? "bg-[#E5B83B]/20 text-[#B45309] dark:text-[#FFE28A] border-2 border-[#E5B83B] shadow-[0_0_15px_rgba(229,184,59,0.35)] scale-[1.02]"
                    : "bg-slate-100/90 dark:bg-white/5 text-slate-700 dark:text-slate-300 hover:bg-slate-200/90 dark:hover:bg-white/10 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-white/10 shadow-sm"
                }`}
              >
                <span 
                  className="h-2 w-2 rounded-full shrink-0" 
                  style={{ background: item.color }} 
                />
                <span>{item.label}</span>
                {isSelected && (
                  <CheckCircle2 size={13} className="text-[#B45309] dark:text-[#FFE28A]" />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Address Input */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-slate-600 dark:text-slate-400">
          Wallet address (TRON, EVM hex, BTC, or Case Entity ID)
        </label>
        <Compose
          value={address}
          onChange={handleAddressChange}
          placeholder="Enter wallet address (0x... or T...)"
          mentions={[{ id: "rpc", label: "rpc-node" }]}
          commands={[{ id: "polygon", label: "polygon", hint: "chain" }]}
        />
      </div>

      {/* Trace Depth (Hops) Selection */}
      <div className="mt-4">
        <div className="flex items-center justify-between mb-1.5 text-xs font-medium text-slate-600 dark:text-slate-400">
          <span>Trace Depth (Hops)</span>
          <span className="text-[10px] text-[#d8b84d]">
            {hops === 0 ? "Target wallet transactions only" : `${hops} hop traversal active`}
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {HOP_OPTIONS.map((opt) => (
            <button
              type="button"
              key={opt.value}
              onClick={() => setHops(opt.value)}
              className={`rounded-xl px-2.5 py-2 text-left transition-all cursor-pointer border ${
                hops === opt.value
                  ? "bg-[#E5B83B]/20 border-[#E5B83B] text-[#B45309] dark:text-[#FFE28A] font-bold shadow-[0_0_12px_rgba(229,184,59,0.25)]"
                  : "bg-slate-100/80 dark:bg-white/5 border-slate-200 dark:border-white/10 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-white/10"
              }`}
            >
              <div className="text-xs font-semibold flex items-center justify-between">
                <span>{opt.value} {opt.value === 1 ? "Hop" : "Hops"}</span>
                {hops === opt.value && <CheckCircle2 size={12} className="text-[#B45309] dark:text-[#FFE28A]" />}
              </div>
              <div className="text-[9px] text-slate-400 leading-tight mt-0.5 truncate" title={opt.desc}>
                {opt.desc}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* FIR / Case No Input */}
      <div className="mt-4">
        <label className="mb-1.5 block text-xs font-medium text-slate-600 dark:text-slate-400">FIR / NCRP complaint reference</label>
        <div className="glass-input flex items-center gap-2 rounded-xl px-3.5 py-2.5 focus-within:border-[#d8b84d] transition">
          <Search size={14} className="text-slate-400 dark:text-slate-500 shrink-0" />
          <input
            value={firNo}
            onChange={(e) => setFirNo(e.target.value)}
            className="mono w-full bg-transparent text-sm text-slate-900 dark:text-slate-100 outline-none placeholder:text-slate-400 dark:placeholder:text-slate-600"
            placeholder="e.g. SIH/2026/00412"
          />
        </div>
      </div>

      {/* Start Trace Action Button (Rolex Luxury Gold Gradient) */}
      <button
        type="button"
        onClick={() => onTrace(address, chain, firNo, hops)}
        disabled={loading || !address}
        className="rolex-gold-btn mt-5 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3.5 text-sm font-extrabold tracking-wide transition disabled:opacity-50 cursor-pointer"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin text-[#150F00]" />
        ) : (
          <Search className="h-4 w-4 text-[#150F00]" strokeWidth={2.5} />
        )}
        <span className="text-[#150F00] font-mono">
          {loading 
            ? `Traversing live blockchain (${elapsedTime.toFixed(2)}s)...` 
            : `Start autonomous trace (${hops} ${hops === 1 ? "hop" : "hops"})`}
        </span>
      </button>

      {/* Footer Info */}
      <div className="mt-3 flex items-center justify-between text-[10px] text-slate-500">
        <span className="flex items-center gap-1">
          <Eye size={12} className="text-emerald-400" /> Continuous surveillance: ACTIVE (25s cadence)
        </span>
        <span className="text-[#d8b84d] font-medium">Auto-detection: ENABLED</span>
      </div>
    </div>
  );
}
