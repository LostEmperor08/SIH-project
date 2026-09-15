import React, { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Activity, ArrowLeft, ArrowRight, Bell, BookOpen, ChevronDown, Clock3, Command, Home, 
  ExternalLink, FileText, Layers, LogOut, Menu, Moon, Palette, Search, Settings, 
  Shield, ShieldCheck, Sparkles, Sun, User, Wifi, X, Zap 
} from "lucide-react";
import { CommandPaletteModal } from "./CommandPaletteModal.jsx";
import ChakravyuhLogo from "./ChakravyuhLogo.jsx";
import { useTheme } from "../lib/ThemeContext.jsx";

const workspaceLinks = [
  { id: "landing", label: "Home", icon: Home },
  { id: "workspace", label: "Live Attribution", icon: Activity },
  { id: "watchlist", label: "Watchlist", icon: Shield },
  { id: "dossier", label: "Legal Dossier", icon: FileText },
  { id: "evidence", label: "Evidence Ledger", icon: BookOpen },
];

const landingNavLinks = [
  { id: "landing", label: "Home", icon: Home },
  { id: "evidence", label: "Active Stream", icon: Zap },
  { id: "how-it-works", label: "How It Works", icon: Sparkles },
];

const notifications = [
  { title: "New attribution match", body: "95% VASP confidence signal detected.", time: "2 min ago" },
  { title: "Evidence window reminder", body: "Section 91 window closes in 3 hours.", time: "18 min ago" },
  { title: "Node sync complete", body: "All 12 chains re-synced successfully.", time: "1 hr ago" },
];

export function WorkspaceNav({ activeRoute, onNavigate, variant = "workspace" }) {
  const { glassMode, toggleGlassMode } = useTheme();
  const isLanding = variant === "landing";
  const isAuth = variant === "auth";
  const navLinks = isLanding ? landingNavLinks : (isAuth ? [] : workspaceLinks);

  const [notifOpen, setNotifOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [currentTime, setCurrentTime] = useState("");

  const notifRef = useRef(null);
  const settingsRef = useRef(null);

  // Live IST Clock
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  // Popover dismissal: pointer outside, focus moving away, or Escape. Focus
  // matters as much as the click — tabbing out of a popover should close it.
  useEffect(() => {
    const away = (e) => {
      if (notifRef.current && !notifRef.current.contains(e.target)) setNotifOpen(false);
      if (settingsRef.current && !settingsRef.current.contains(e.target)) setSettingsOpen(false);
    };
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      setNotifOpen(false);
      setSettingsOpen(false);
    };
    const closeAll = () => {
      setNotifOpen(false);
      setSettingsOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("focusin", away);
    document.addEventListener("keydown", onKey);
    window.addEventListener("blur", closeAll);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("focusin", away);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", closeAll);
    };
  }, []);

  // Render High-End Settings & Appearance Dropdown
  const renderSettingsDropdown = () => (
    <motion.div
      initial={{ opacity: 0, y: -10, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -10, scale: 0.96 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="cv-ios-popover cv-user-popover w-[320px] sm:w-[340px]"
      role="dialog"
      aria-label="Settings and profile menu"
    >
      {/* Officer Profile Header */}
      <div className="p-4 border-b border-slate-200 dark:border-white/10 bg-slate-50/50 dark:bg-white/[0.02]">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#E5B83B]/30 to-emerald-900 border border-[#E5B83B]/50 text-[#FFE28A] font-extrabold text-sm shadow-md">
            AS
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <strong className="block text-xs font-bold text-slate-900 dark:text-white truncate">Inspector A. Sharma</strong>
              <span className="shrink-0 rounded bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.2 text-[8px] font-bold text-emerald-700 dark:text-emerald-300">
                VERIFIED
              </span>
            </div>
            <p className="text-[10px] text-slate-500 dark:text-slate-400 truncate">Cyber Crime PS · I4C Operations</p>
          </div>
        </div>

        {!isLanding && !isAuth && (
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              type="button"
              className="flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-white/5 py-1.5 px-2 text-[11px] font-bold text-slate-800 dark:text-slate-200 hover:border-[#E5B83B]/60 hover:text-[#B45309] dark:hover:text-[#FFE28A] transition cursor-pointer"
              onClick={() => { setSettingsOpen(false); onNavigate("profile"); }}
            >
              <User size={12} className="text-[#E5B83B]" />
              <span>Officer Profile</span>
            </button>
            <button
              type="button"
              className="flex items-center justify-center gap-1.5 rounded-lg border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-white/5 py-1.5 px-2 text-[11px] font-bold text-slate-800 dark:text-slate-200 hover:border-[#E5B83B]/60 hover:text-[#B45309] dark:hover:text-[#FFE28A] transition cursor-pointer"
              onClick={() => { setSettingsOpen(false); onNavigate("profile"); }}
            >
              <ShieldCheck size={12} className="text-emerald-500" />
              <span>Profile</span>
            </button>
          </div>
        )}
      </div>

      {/* Settings Controls Section */}
      <div className="p-3.5 space-y-3">
        {/* Theme Mode Switcher */}
        {/* Glassmorphism FX Switcher */}
        <div className="flex items-center justify-between rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50/50 dark:bg-white/[0.02] p-2.5">
          <div className="flex items-center gap-2.5">
            <div className={`flex h-8 w-8 items-center justify-center rounded-lg border transition ${
              glassMode 
                ? "bg-[#E5B83B]/15 border-[#E5B83B]/50 text-[#B45309] dark:text-[#FFE28A] shadow-[0_0_12px_rgba(229,184,59,0.3)]" 
                : "bg-slate-100 dark:bg-white/5 border-slate-200 dark:border-white/10 text-slate-400"
            }`}>
              <Layers size={15} />
            </div>
            <div>
              <div className="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                <span>Glassmorphism UI</span>
                {glassMode && (
                  <span className="rounded-full bg-emerald-500/20 px-1.5 py-0.2 text-[8px] font-bold text-emerald-700 dark:text-emerald-300 border border-emerald-500/30">
                    ACTIVE
                  </span>
                )}
              </div>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">Frosted translucency &amp; blur</p>
            </div>
          </div>

          <button
            type="button"
            onClick={toggleGlassMode}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
              glassMode ? "bg-[#006039] border-[#E5B83B]/60 shadow-[0_0_12px_rgba(16,185,129,0.4)]" : "bg-slate-300 dark:bg-slate-700"
            }`}
            role="switch"
            aria-checked={glassMode}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                glassMode ? "translate-x-5 bg-[#FFE28A]" : "translate-x-0"
              }`}
            />
          </button>
        </div>
      </div>

      {/* Footer Navigation / Sign Out */}
      <div className="p-2 border-t border-slate-200 dark:border-white/10 bg-slate-50/50 dark:bg-white/[0.02]">
        <button
          type="button"
          className="w-full flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition cursor-pointer"
          onClick={() => { setSettingsOpen(false); onNavigate(isLanding ? "login" : "landing"); }}
        >
          <LogOut size={13} />
          <span>{isLanding ? "Access Officer Login" : "Lock Session / Sign Out"}</span>
        </button>
      </div>
    </motion.div>
  );


  return (
    <>
      {/* Backdrop for mobile menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-md"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      {/* ── Apple / macOS Dynamic Floating Dock Navbar ── */}
      <header className="cv-dock-navbar cv-shared-sticky-nav">
        {/* Left: Brand Lockup */}
        <div className="flex items-center justify-start min-w-0">
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
            type="button"
            className="cv-brand-button"
            onClick={() => onNavigate("landing")}
            aria-label="Go to landing page"
          >
            <div className="cv-dashboard-brand">
              <ChakravyuhLogo />
              <span className="cv-dashboard-brand-meta">
                <b>I4C</b>
                NATIONAL ATTRIBUTION
              </span>
            </div>
          </motion.button>
        </div>

        {/* Center: Floating Dock Pill Menu */}
        <div className="flex items-center justify-center">
          {navLinks.length > 0 && (
            <nav className="cv-dock-pill relative" aria-label="Primary navigation">
              {navLinks.map(({ id, label, icon: Icon }) => {
                const isActive = activeRoute === id;
                return (
                  <motion.button
                    type="button"
                    key={id}
                    whileTap={{ scale: 0.94 }}
                    className={`cv-dock-link relative z-10 ${isActive ? "cv-dock-link--active" : "text-slate-400 hover:text-slate-200"}`}
                    onClick={() => { onNavigate(id); setMobileOpen(false); }}
                    title={label}
                  >
                    <div className={`cv-dock-icon-tile ${isActive ? "cv-dock-icon-tile--active" : ""}`}>
                      <Icon size={14} strokeWidth={2.2} />
                    </div>
                    <span className="cv-dock-label">{label}</span>
                    
                    {isActive && (
                      <motion.div
                        layoutId="cv-dock-active-pill"
                        className="cv-dock-active-pill absolute inset-0 -z-10 rounded-full bg-gradient-to-r from-[#006039] to-[#059669] border border-[#E5B83B]/60 shadow-[0_0_20px_rgba(16,185,129,0.4),0_0_12px_rgba(229,184,59,0.35)]"
                        transition={{
                          type: "spring",
                          stiffness: 450,
                          damping: 32,
                        }}
                      />
                    )}
                  </motion.button>
                );
              })}
            </nav>
          )}

          {isAuth && (
            <div className="hidden md:inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-[10px] font-mono tracking-wider text-[#FFE28A] border border-[#E5B83B]/40 bg-[#08291D]/80 shadow-sm backdrop-blur-md">
              <span className="w-1.5 h-1.5 rounded-full bg-[#E5B83B] animate-pulse" />
              <span>SECURED LAW ENFORCEMENT GATEWAY</span>
            </div>
          )}
        </div>

        {/* Right: Dock Utilities & Actions */}
        <div className="flex items-center justify-end">
          <div className="cv-dock-actions">
            {isAuth ? (
              /* Auth Page Navigation */
              <div className="flex items-center gap-2">
                {/* Settings dropdown for Auth pages */}
                <div ref={settingsRef} className="relative">
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    type="button"
                    className={`cv-action-button ${settingsOpen ? "cv-action-button--open" : ""}`}
                    aria-label="Settings & Appearance"
                    onClick={() => setSettingsOpen(o => !o)}
                    title="Settings & Appearance (Theme, Glassmorphism)"
                  >
                    <Settings size={16} className="text-[#E5B83B]" />
                  </motion.button>

                  <AnimatePresence>
                    {settingsOpen && renderSettingsDropdown()}
                  </AnimatePresence>
                </div>

                <motion.button
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.96 }}
                  type="button"
                  onClick={() => onNavigate("landing")}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200/80 dark:border-white/15 bg-white/70 dark:bg-white/5 px-3.5 py-2 text-xs font-bold text-slate-800 dark:text-slate-200 hover:border-[#E5B83B]/50 hover:text-[#E5B83B] transition shadow-sm cursor-pointer"
                >
                  <ArrowLeft size={13} strokeWidth={2.5} />
                  <span>Overview</span>
                </motion.button>
              </div>
            ) : isLanding ? (
              /* Landing Page CTAs */
              <div className="flex items-center gap-2">
                <motion.button
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.96 }}
                  type="button"
                  onClick={() => onNavigate("login")}
                  className="hidden sm:inline-flex items-center gap-1.5 rounded-xl border border-slate-200/80 dark:border-white/15 bg-white/70 dark:bg-white/5 px-3.5 py-2 text-xs font-bold text-slate-800 dark:text-slate-200 hover:border-[#E5B83B]/50 hover:text-[#E5B83B] transition shadow-sm cursor-pointer"
                >
                  Sign In
                </motion.button>

                <motion.button
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.96 }}
                  type="button"
                  onClick={() => onNavigate("dashboard")}
                  className="rolex-gold-btn cv-console-btn inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] font-extrabold sm:px-4 sm:py-2 sm:text-xs cursor-pointer"
                  aria-label="Open Console"
                >
                  <span className="cv-console-btn__label text-[#150F00]">Open Console</span>
                  <ArrowRight size={13} strokeWidth={2.5} className="text-[#150F00]" />
                </motion.button>
              </div>
            ) : (
              /* Workspace Dashboard Utilities */
              <>
                {/* Quick Search Launcher (⌘K) */}
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  type="button"
                  className="cv-action-button cv-search-dock-btn cv-dock-desktop-only"
                  aria-label="Quick Command Palette"
                  onClick={() => setIsSearchOpen(true)}
                  title="Quick Intelligence Search (⌘K)"
                >
                  <Search size={15} />
                  <span className="cv-shortcut-badge hidden xl:inline-block">⌘K</span>
                </motion.button>

                {/* Notification Bell */}
                <div ref={notifRef} className="relative cv-dock-desktop-only">
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    type="button"
                    className={`cv-action-button ${notifOpen ? "cv-action-button--open" : ""}`}
                    aria-label="Notifications"
                    aria-expanded={notifOpen}
                    onClick={() => { setNotifOpen(o => !o); setSettingsOpen(false); }}
                  >
                    <Bell size={16} strokeWidth={2} />
                    <motion.span 
                      initial={{ scale: 0.8 }} 
                      animate={{ scale: [1, 1.2, 1] }} 
                      transition={{ repeat: Infinity, duration: 3, repeatDelay: 2 }} 
                      className="cv-badge-count" 
                      aria-label="3 new notifications"
                    >
                      3
                    </motion.span>
                  </motion.button>

                  <AnimatePresence>
                    {notifOpen && (
                      <motion.div
                        initial={{ opacity: 0, y: -10, scale: 0.96 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: -10, scale: 0.96 }}
                        transition={{ duration: 0.18, ease: "easeOut" }}
                        className="cv-ios-popover cv-notif-popover"
                        role="dialog"
                        aria-label="Notifications"
                      >
                        <div className="cv-popover-header">
                          <span className="flex items-center gap-1.5">
                            <Zap size={13} className="text-[#d8b84d]" /> Operations Signals
                          </span>
                          <span className="cv-popover-badge">03 UNREAD</span>
                        </div>
                        <div className="divide-y divide-white/5 max-h-[300px] overflow-y-auto">
                          {notifications.map((n) => (
                            <div key={n.title} className="p-3.5 hover:bg-white/[0.04] transition flex items-start gap-3">
                              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-950/60 border border-emerald-500/30 text-emerald-400">
                                <Bell size={12} />
                              </div>
                              <div className="min-w-0 flex-1">
                                <strong className="block text-xs font-semibold text-slate-200">{n.title}</strong>
                                <p className="mt-0.5 text-[11px] text-slate-400">{n.body}</p>
                                <small className="mt-1 flex items-center gap-1 text-[9px] text-slate-500 font-mono">
                                  <Clock3 size={10} /> {n.time}
                                </small>
                              </div>
                            </div>
                          ))}
                        </div>
                        <button
                          type="button"
                          className="w-full border-t border-white/10 p-3 text-center text-xs font-semibold text-[#d8b84d] hover:bg-[#d8b84d]/10 transition cursor-pointer"
                          onClick={() => { setNotifOpen(false); onNavigate("notifications"); }}
                        >
                          View all intelligence alerts →
                        </button>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                {/* Unified Settings & Profile Dropdown Button */}
                <div ref={settingsRef} className="relative">
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.96 }}
                    type="button"
                    className={`cv-profile-button ${settingsOpen ? "cv-profile-button--open" : ""}`}
                    aria-label="Settings and profile menu"
                    aria-expanded={settingsOpen}
                    onClick={() => { setSettingsOpen(o => !o); setNotifOpen(false); }}
                  >
                    <div className="cv-avatar-tile">AS</div>
                    <span className="cv-user-label hidden sm:inline-block">Insp. A. Sharma</span>
                    <ChevronDown size={12} strokeWidth={2.5} className="text-slate-400" />
                  </motion.button>

                  <AnimatePresence>
                    {settingsOpen && renderSettingsDropdown()}
                  </AnimatePresence>
                </div>
              </>
            )}
          </div>

          {/* Mobile Menu Toggle (only if links present) */}
          {navLinks.length > 0 && (
            <button
              type="button"
              className="cv-mobile-btn lg:hidden ml-2"
              aria-label={mobileOpen ? "Close menu" : "Open menu"}
              onClick={() => setMobileOpen(o => !o)}
            >
              {mobileOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          )}
        </div>
      </header>

      {/* Mobile Navigation Drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, y: -15 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -15 }}
            className="cv-mobile-dropdown lg:hidden"
          >
            {navLinks.map(({ id, label, icon: Icon }) => (
              <button
                type="button"
                key={id}
                className={`flex items-center gap-3 w-full p-3 rounded-xl text-xs font-semibold transition ${
                  activeRoute === id 
                    ? "bg-slate-900 text-white dark:bg-[rgba(216,184,77,0.15)] dark:text-[#d8b84d] dark:border dark:border-[rgba(216,184,77,0.3)]" 
                    : "text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/5"
                }`}
                onClick={() => { onNavigate(id); setMobileOpen(false); }}
              >
                <Icon size={16} />
                <span>{label}</span>
              </button>
            ))}
            <div className="border-t border-slate-200 dark:border-white/10 pt-2 mt-2 space-y-1">
              {!isLanding && !isAuth && (
                <>
                  <button
                    type="button"
                    className="cv-mobile-link flex items-center gap-3 w-full p-3 rounded-xl text-xs font-semibold text-slate-300 hover:bg-white/5 transition"
                    onClick={() => { setIsSearchOpen(true); setMobileOpen(false); }}
                  >
                    <Search size={15} /> Quick search
                  </button>
                  <button
                    type="button"
                    className="cv-mobile-link flex items-center gap-3 w-full p-3 rounded-xl text-xs font-semibold text-slate-300 hover:bg-white/5 transition"
                    onClick={() => { onNavigate("notifications"); setMobileOpen(false); }}
                  >
                    <Bell size={15} /> Intelligence alerts
                  </button>
                  <button
                    type="button"
                    className="cv-mobile-link flex items-center gap-3 w-full p-3 rounded-xl text-xs font-semibold text-slate-300 hover:bg-white/5 transition"
                    onClick={() => { onNavigate("profile"); setMobileOpen(false); }}
                  >
                    <User size={15} /> Profile
                  </button>
                </>
              )}
              {isLanding ? (
                <>
                  <button
                    type="button"
                    className="cv-sheet-btn cv-sheet-btn--primary"
                    onClick={() => { onNavigate("dashboard"); setMobileOpen(false); }}
                  >
                    <Zap size={15} /> Open Console
                  </button>
                  <button
                    type="button"
                    className="cv-sheet-btn cv-sheet-btn--ghost"
                    onClick={() => { onNavigate("login"); setMobileOpen(false); }}
                  >
                    <User size={15} /> Sign In
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="cv-sheet-btn cv-sheet-btn--danger"
                  onClick={() => { onNavigate("landing"); setMobileOpen(false); }}
                >
                  <LogOut size={15} /> Sign out
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Command Palette Quick Search Modal (⌘K) ── */}
      <CommandPaletteModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        onNavigate={onNavigate}
      />
    </>
  );
}
