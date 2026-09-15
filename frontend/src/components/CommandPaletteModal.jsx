import React, { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { 
  Activity, ArrowRight, BookOpen, Clock, Command, 
  FileText, Fingerprint, Search, Shield, Sparkles, X, Zap 
} from "lucide-react";

export function CommandPaletteModal({ isOpen, onClose, onNavigate, onSelectWallet }) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (isOpen) onClose();
        else onClose(false);
      }
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const quickActions = [
    { id: "trace", title: "Trace Suspect TRON Mule", desc: "TX7sK...victim", icon: Zap, category: "Trace", action: () => { onSelectWallet?.("TX7sK...victim"); onNavigate?.("workspace"); onClose(); } },
    { id: "poly", title: "Inspect Polygon Layering Node", desc: "0xe6d634289cf30114041b63e6358", icon: Fingerprint, category: "Trace", action: () => { onSelectWallet?.("0xe6d634289cf30114041b63e6358"); onNavigate?.("workspace"); onClose(); } },
    { id: "evidence", title: "Open Cryptographic Evidence Ledger", desc: "49 on-chain Section 65B records", icon: BookOpen, category: "Navigation", action: () => { onNavigate?.("evidence"); onClose(); } },
    { id: "watchlist", title: "Open Watchlist Queue", desc: "Autonomous 24/7 surveillance", icon: Shield, category: "Navigation", action: () => { onNavigate?.("watchlist"); onClose(); } },
    { id: "dossier", title: "Generate Section 91 Legal Notice", desc: "Statutory BNSS Sec 94 format", icon: FileText, category: "Actions", action: () => { onNavigate?.("dossier"); onClose(); } },
  ];

  const filtered = quickActions.filter(a => 
    a.title.toLowerCase().includes(query.toLowerCase()) || 
    a.desc.toLowerCase().includes(query.toLowerCase()) ||
    a.category.toLowerCase().includes(query.toLowerCase())
  );

  const modal = (
    <div className="fixed inset-0 z-[999999] flex items-start justify-center pt-24 p-4">
      <div 
        className="fixed inset-0 bg-black/80 backdrop-blur-xl animate-in fade-in" 
        onClick={onClose} 
        aria-hidden="true" 
      />

      <div 
        className="relative z-10 w-full max-w-xl rounded-3xl border border-white/20 bg-[#05140c]/98 text-slate-100 shadow-[0_30px_90px_rgba(0,0,0,0.95),0_0_50px_rgba(216,184,77,0.2)] backdrop-blur-3xl overflow-hidden animate-in zoom-in-95 duration-200"
      >
        {/* Search Input Bar */}
        <div className="flex items-center gap-3 border-b border-white/10 px-5 py-4 bg-black/40">
          <Search size={20} className="text-[#d8b84d]" />
          <input
            autoFocus
            type="text"
            placeholder="Type a command, address, or switch view... (ESC to close)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500 font-sans"
          />
          <button 
            type="button" 
            onClick={onClose}
            className="rounded-xl p-1 text-slate-400 hover:text-white hover:bg-white/10 transition"
          >
            <X size={18} />
          </button>
        </div>

        {/* Action Items List */}
        <div className="max-h-[340px] overflow-y-auto p-3 space-y-1.5">
          <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Suggested Quick Actions
          </div>
          {filtered.length > 0 ? (
            filtered.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={item.action}
                  className="flex items-center justify-between w-full p-3.5 rounded-2xl hover:bg-white/[0.08] text-left transition group cursor-pointer"
                >
                  <div className="flex items-center gap-3.5">
                    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#d8b84d]/15 text-[#d8b84d] border border-[#d8b84d]/30 group-hover:scale-105 transition-transform">
                      <Icon size={17} />
                    </div>
                    <div>
                      <strong className="block text-xs font-semibold text-slate-200 group-hover:text-white">
                        {item.title}
                      </strong>
                      <span className="text-[11px] text-slate-400 font-mono">
                        {item.desc}
                      </span>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold text-slate-400 rounded-lg border border-white/10 px-2.5 py-1 group-hover:border-[#d8b84d]/40 group-hover:text-[#d8b84d]">
                    {item.category}
                  </span>
                </button>
              );
            })
          ) : (
            <div className="p-6 text-center text-xs text-slate-500">
              No matching commands or entities found for "{query}"
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-white/10 bg-black/60 px-5 py-3 text-[11px] text-slate-400 flex items-center justify-between">
          <span className="flex items-center gap-1.5">
            <Command size={13} className="text-[#d8b84d]" /> CHAKRAVYUH Quick Intelligence
          </span>
          <span className="font-mono text-[10px]">Press ↵ to select</span>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
