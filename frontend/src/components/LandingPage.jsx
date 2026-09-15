import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { motion, useSpring, useTransform, useScroll } from "framer-motion";
import { 
  Activity, ArrowRight, BookOpen, Check, CheckCircle2, 
  ChevronRight, Clock3, Copy, Database, ExternalLink, 
  FileSpreadsheet, FileText, Fingerprint, Layers, 
  Plus, RefreshCw, Search, Shield, ShieldAlert, 
  Sparkles, Terminal, Wallet, Zap 
} from "lucide-react";
import ChakravyuhLogo from "./ChakravyuhLogo.jsx";
import { WorkspaceNav } from "./WorkspaceNav.jsx";
import HowItWorksSection from "./HowItWorksSection.jsx";
import BackToTop from "./BackToTop.jsx";
import { useTheme } from "../lib/ThemeContext.jsx";

export function LandingPage() {
  const navigate = useNavigate();
  const { theme } = useTheme();
  const isLight = theme === "light";
  const TRACE_DURATION_SECONDS = 540;

  // ── Antigravity Physics Engine State ──
  const [p, setP] = useState(0);
  const [touched, setTouched] = useState(false);
  const [wide, setWide] = useState(true);
  const [activeNav, setActiveNav] = useState("hero");

  // Physics Refs for Zero-Reflow 120fps rAF Lerp Loop
  const targetProgressRef = useRef(0);
  const currentProgressRef = useRef(0);
  const isDraggingRef = useRef(false);
  const dragRef = useRef(null);
  const videoRef = useRef(null);
  const cachedRangeRef = useRef(1600);

  const pts = useMemo(() => [[188, 417], [424, 293], [698, 302], [640, 581], [456, 751], [723, 430]], []);

  const kfs = useMemo(() => [
    { at: 0, floor: 0, name: "THE COMPROMISED SEED" },
    { at: 12, floor: 0, name: "PEEL CHAIN SPLINTER" },
    { at: 24, floor: 0.10, name: "OBFUSCATION LABYRINTH" },
    { at: 38, floor: 0.22, name: "MULTI-HOP GRAPH" },
    { at: 51, floor: 0.28, name: "EXCHANGE FUNNEL" },
    { at: 64, floor: 0.34, name: "STATUTORY DOSSIER" },
    { at: 77, floor: 0.42, name: "I4C COMMAND CENTER" },
    { at: 88, floor: 0.58, name: "NATIONAL CYBER GRID" },
    { at: 96, floor: 1, name: "ORBITAL CHAKRAVYUH" }
  ], []);

  const segs = useMemo(() => {
    const out = [];
    let total = 0;
    for (let i = 1; i < pts.length; i++) {
      const [ax, ay] = pts[i - 1], [bx, by] = pts[i];
      const len = Math.hypot(bx - ax, by - ay);
      out.push({ ax, ay, bx, by, len, start: total });
      total += len;
    }
    return { out, total };
  }, [pts]);

  // Antigravity Range Calculator with Cached Dimensions
  const updateRange = useCallback(() => {
    const h = window.innerHeight || 800;
    cachedRangeRef.current = Math.max(240, h * 2);
    setWide(window.innerWidth >= 800);
  }, []);

  // ── Video Scrub Optimization Routine (Clamped, Rounded to 3 decimals, Anti-Stutter) ──
  const syncVideoScrub = useCallback((progressRatio) => {
    if (!videoRef.current) return;
    const vid = videoRef.current;
    if (!vid.duration || isNaN(vid.duration)) return;

    // Clamp progress between 0 and 1
    const clampedProgress = Math.max(0, Math.min(1, progressRatio));
    // Round target time to 3 decimal places to avoid micro-stutters
    const targetTime = Math.round((clampedProgress * vid.duration) * 1000) / 1000;

    // Throttled dirty check to prevent decoder thrashing
    if (Math.abs(vid.currentTime - targetTime) > 0.008) {
      vid.currentTime = targetTime;
    }
  }, []);

  // ── 120fps Antigravity Physics Engine Loop ──
  useEffect(() => {
    updateRange();
    window.addEventListener("resize", updateRange, { passive: true });

    let lastScrollY = window.scrollY || document.documentElement.scrollTop || 0;

    const onPassiveScroll = () => {
      const y = window.scrollY || document.documentElement.scrollTop || 0;
      lastScrollY = y;
      const range = cachedRangeRef.current;
      const clamped = Math.max(0, Math.min(1, y / range));
      targetProgressRef.current = clamped * 100;

      if (y > 2 && !touched) {
        setTouched(true);
      }

      // Scroll Spy for Navigation Links
      if (y < range) {
        setActiveNav("hero");
      } else {
        const missionEl = document.getElementById("mission-section");
        const evidenceEl = document.getElementById("evidence");
        if (evidenceEl && y >= evidenceEl.offsetTop - 220) {
          setActiveNav("evidence");
        } else if (missionEl && y >= missionEl.offsetTop - 220) {
          setActiveNav("mission-section");
        }
      }
    };

    window.addEventListener("scroll", onPassiveScroll, { passive: true });

    let lastTime = performance.now();
    let rafId;

    // 120fps Exponential Antigravity Damping (Low Mass, High Damping, Zero Friction)
    const physicsTick = (now) => {
      const dt = Math.min((now - lastTime) / 1000, 0.1);
      lastTime = now;

      if (!touched && !isDraggingRef.current) {
        // Idle weightless drift
        targetProgressRef.current = targetProgressRef.current >= 100 
          ? 0 
          : targetProgressRef.current + (dt * 100) / TRACE_DURATION_SECONDS;
      }

      // Framerate-independent exponential lerp (antigravity inertia)
      const lerpFactor = isDraggingRef.current ? 0.35 : (1 - Math.exp(-dt * 14));
      const diff = targetProgressRef.current - currentProgressRef.current;

      if (Math.abs(diff) > 0.001) {
        currentProgressRef.current += diff * lerpFactor;
        const clampedVal = Math.max(0, Math.min(100, currentProgressRef.current));
        setP(clampedVal);
        syncVideoScrub(clampedVal / 100);
      }

      rafId = requestAnimationFrame(physicsTick);
    };

    rafId = requestAnimationFrame(physicsTick);

    const onPointerMove = (e) => {
      if (!isDraggingRef.current || !dragRef.current) return;
      const r = dragRef.current.getBoundingClientRect();
      const f = Math.max(0, Math.min(1, (e.clientX - r.left) / Math.max(1, r.width)));
      targetProgressRef.current = f * 100;
      currentProgressRef.current = f * 100;
      window.scrollTo({ top: f * cachedRangeRef.current, behavior: "auto" });
      setP(f * 100);
      setTouched(true);
      syncVideoScrub(f);
    };

    const onPointerUp = () => {
      isDraggingRef.current = false;
    };

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerup", onPointerUp, { passive: true });

    return () => {
      window.removeEventListener("resize", updateRange);
      window.removeEventListener("scroll", onPassiveScroll);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      cancelAnimationFrame(rafId);
    };
  }, [touched, updateRange, syncVideoScrub]);

  // Derived Values for SVG Radar
  const cl = (v, a, b) => Math.max(a, Math.min(b, v));
  const z0 = 3.6;
  const z = z0 * Math.pow(0.155, p / 100);
  const zoomT = `translate(500 500) scale(${z.toFixed(4)}) translate(-500 -500)`;

  const layers = {};
  kfs.forEach((k, i) => {
    const fadeIn = cl((p - (k.at - 16)) / 12, 0, 1);
    const decay = cl((p - (k.at + 12)) / 22, 0, 1);
    layers[`L${i + 1}`] = +(fadeIn * (1 - decay * (1 - k.floor))).toFixed(3);
  });

  const tp = cl((p - 22) / 40, 0, 1) * 100;
  const { out, total } = segs;
  const d = (tp / 100) * total;
  let dotX = pts[0][0], dotY = pts[0][1];
  for (const s of out) {
    if (d >= s.start) {
      const f = cl((d - s.start) / s.len, 0, 1);
      dotX = s.ax + (s.bx - s.ax) * f;
      dotY = s.ay + (s.by - s.ay) * f;
    }
  }

  const thresh = [0, ...out.map((s) => ((s.start + s.len) / total) * 100)];
  const nodeColors = {};
  const nodeOpacities = {};
  const textColors = {};
  thresh.forEach((tVal, i) => {
    const on = i === 0 ? true : tp >= tVal - 0.6;
    const amber = i === 5;
    nodeColors[`c${i}`] = on ? (amber ? "#F59E0B" : "#10B981") : (isLight ? "#CBD5E1" : "#39414A");
    nodeOpacities[`o${i}`] = on ? 1 : 0;
    textColors[`t${i}`] = on ? (amber ? (isLight ? "#B45309" : "#FDE68A") : (isLight ? "#059669" : "#D6FBEA")) : (isLight ? "#94A3B8" : "#5C646D");
  });

  const hopStage = p < 18 ? "INGEST" : p < 42 ? "PEEL CHAIN" : p < 66 ? "MIXER TRAVERSAL" : "VASP CLUSTER IDENTIFIED";
  const phase =
    tp < thresh[1] ? "INGEST · NCRP COMPLAINT 0x7b51…ped1" :
    tp < thresh[2] ? "HOP 01 · PEEL CHAIN DETECTED" :
    tp < thresh[3] ? "HOP 02 · MIXER PASS-THROUGH" :
    tp < thresh[4] ? "HOP 03 · CROSS-CHAIN BRIDGE TRC-20" :
    tp < 99.4 ? "HOP 04 · MULE CLUSTER ×14 RESOLVING" :
    "VASP IDENTIFIED · TIER-1 EXCHANGE — HOT WALLET 4";

  const kfi = kfs.reduce((acc, k, i) => (p >= k.at - 6 ? i : acc), 0);
  const timeVal = (p / 100) * 540;
  const pad = (n, w) => String(Math.floor(n)).padStart(w, "0");
  const risk = Math.round(38 + (p / 100) * 57);

  const dashOff = 100 - tp;
  const pw = p.toFixed(1) + "%";
  const tc = "00:" + pad(timeVal / 60, 2) + ":" + pad(timeVal % 60, 2) + "." + pad((timeVal * 100) % 100, 2);
  const kfName = "KEYFRAME " + pad(kfi + 1, 2) + " · " + kfs[kfi].name;
  const volume = (412.5 * cl(tp, 0, 100) / 100).toFixed(1);
  const chainName = p < 40 ? "POLYGON" : p < 70 ? "POLYGON / TRC-20" : "POLYGON / TRC-20 / ETH";
  const riskLabel = p > 88 ? "CRITICAL (" + risk + "%)" : (risk > 70 ? "HIGH (" : "ELEVATED (") + risk + "%)";

  const handleScrubDown = (e) => {
    dragRef.current = e.currentTarget;
    isDragging.current = true;
    const r = e.currentTarget.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (e.clientX - r.left) / Math.max(1, r.width)));
    window.scrollTo({ top: f * range(), behavior: "auto" });
    setP(f * 100);
    setTouched(true);
  };

  const scrollToSection = (id) => {
    if (id === "hero") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: "smooth" });
    }
  };

  // Keep the dock's active pill in step with the band you are reading. The
  // hero is 300vh and the explainer 520vh, so whichever section owns the
  // middle of the viewport is the one to highlight.
  useEffect(() => {
    const bands = [
      ["hero", "landing"],
      ["evidence", "evidence"],
      ["how-it-works", "how-it-works"],
    ];
    let frame = 0;
    const measure = () => {
      frame = 0;
      const mid = window.innerHeight / 2;
      let current = "landing";
      for (const [id, route] of bands) {
        const el = document.getElementById(id);
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        if (rect.top <= mid && rect.bottom > mid) current = route;
      }
      setActiveNav((prev) => (prev === current ? prev : current));
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, []);

  // A deep link such as /#how-it-works scrolls to the band once it has mounted.
  useEffect(() => {
    if (window.location.hash !== "#how-it-works") return undefined;
    const id = window.setTimeout(() => {
      document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth" });
    }, 260);
    return () => window.clearTimeout(id);
  }, []);

  const handleWorkspaceNav = (route) => {
    if (route === "home" || route === "landing") {
      scrollToSection("hero");
    } else if (route === "how-it-works") {
      scrollToSection("how-it-works");
    } else if (route === "hero" || route === "landing") {
      scrollToSection("hero");
    } else if (route === "mission-section" || route === "mission") {
      scrollToSection("mission-section");
    } else if (route === "evidence") {
      scrollToSection("evidence");
    } else if (route === "workbench" || route === "dashboard") {
      navigate("/dashboard");
    } else if (route === "login") {
      navigate("/login");
    } else {
      navigate("/dashboard", { state: { activeTab: route } });
    }
  };

  const navigateToDashboardWithWallet = (wallet) => {
    navigate("/dashboard", { state: { targetWallet: wallet } });
  };

  return (
    <div style={{ background: "transparent", minHeight: "100dvh", overflowX: "clip", color: isLight ? "#0F172A" : "#E7E9EC", fontFamily: "Archivo, Helvetica, Arial, sans-serif", transition: "background 0.3s, color 0.3s" }}>
      <WorkspaceNav variant="landing" activeRoute={activeNav} onNavigate={handleWorkspaceNav} />

      {/* ── 300vh Scrub Scroll Canvas Section ── */}
      <div id="hero" className="transform-gpu will-change-transform will-change-opacity" style={{ position: "relative", height: "300vh", willChange: "transform, opacity", transform: "translate3d(0, 0, 0)" }}>
        <section 
          className="transform-gpu will-change-transform"
          style={{ 
            position: "sticky", 
            top: 0, 
            height: "100dvh", 
            width: "100%", 
            overflow: "hidden", 
            background: "transparent", 
            display: "grid", 
            gridTemplateRows: "96px minmax(0,1fr) 94px", 
            gridTemplateColumns: "minmax(0,1fr) auto auto", 
            transition: "background 0.3s",
            willChange: "transform",
            transform: "translate3d(0, 0, 0)",
            backfaceVisibility: "hidden",
            WebkitBackfaceVisibility: "hidden"
          }}
        >
          
          {/* Scanlines & Grid Overlay */}
          <div style={{ position: "absolute", inset: 0, backgroundImage: isLight ? "repeating-linear-gradient(to bottom, rgba(0,0,0,.012) 0 1px, transparent 1px 4px)" : "repeating-linear-gradient(to bottom, rgba(255,255,255,.028) 0 1px, transparent 1px 4px)", animation: "drift 9s linear infinite", pointerEvents: "none" }} />
          <div style={{ position: "absolute", inset: 0, backgroundImage: isLight ? "linear-gradient(to right, rgba(0,0,0,.03) 1px, transparent 1px), linear-gradient(to bottom, rgba(0,0,0,.03) 1px, transparent 1px)" : "linear-gradient(to right, rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,.025) 1px, transparent 1px)", backgroundSize: "64px 64px", pointerEvents: "none" }} />
          <div style={{ position: "absolute", inset: 0, background: isLight ? "radial-gradient(circle at 62% 50%, rgba(16,185,129,.12), transparent 55%), radial-gradient(circle at 18% 46%, rgba(241,245,249,.95), transparent 62%)" : "radial-gradient(circle at 62% 50%, rgba(16,185,129,.10), transparent 55%), radial-gradient(circle at 18% 46%, rgba(8,9,12,.92), transparent 62%)", pointerEvents: "none" }} />

          {/* ── Center SVG Canvas: 9 Layers & Multi-Hop Traversal ── */}
          {(
            <div 
              className="hero-graphic transform-gpu will-change-transform will-change-opacity"
              style={{ 
                gridRow: "1 / -1", 
                gridColumn: "1 / -1", 
                position: "absolute",
                inset: 0,
                width: "100%",
                minHeight: 0, 
                overflow: "hidden", 
                opacity: isLight ? 0.58 : 0.68,
                zIndex: 1, 
                display: "grid", 
                placeItems: "center", 
                pointerEvents: "none",
                willChange: "transform, opacity",
                transform: "translate3d(0, 0, 0)",
                backfaceVisibility: "hidden",
                WebkitBackfaceVisibility: "hidden"
              }}
            >
              <svg viewBox="0 0 1000 1000" style={{ width: "100%", height: "100%", willChange: "transform", transform: "translate3d(0, 0, 0)" }}>
                <g transform={zoomT}>
                  {/* Layer 9: Orbital Sovereign Shield */}
                  <g opacity={layers.L9}>
                    <g style={{ animation: "sweep 60s linear infinite", transformOrigin: "500px 500px" }}>
                      <circle cx="500" cy="500" r="880" fill="none" stroke={isLight ? "rgba(29,78,216,.35)" : "rgba(245,158,11,.35)"} strokeWidth="3" strokeDasharray="8 92" />
                      <circle cx="500" cy="500" r="836" fill="none" stroke={isLight ? "rgba(11,95,165,.4)" : "rgba(16,185,129,.4)"} strokeWidth="2" strokeDasharray="180 120" />
                    </g>
                    <g style={{ animation: "sweepRev 44s linear infinite", transformOrigin: "500px 500px" }}>
                      <circle cx="500" cy="500" r="792" fill="none" stroke={isLight ? "rgba(11,95,165,.3)" : "rgba(16,185,129,.3)"} strokeWidth="2" strokeDasharray="40 72" />
                    </g>
                    <text x="500" y="-430" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="30" letterSpacing="8" fill={isLight ? "#059669" : "#6EE7B7"}>CHAKRAVYUH SOVEREIGN SHIELD</text>
                  </g>

                  {/* Layer 8: National Cyber Grid */}
                  <g opacity={layers.L8}>
                    <g stroke={isLight ? "rgba(29,78,216,.25)" : "rgba(245,158,11,.25)"} strokeWidth="1.5">
                      <line x1="500" y1="500" x2="1166" y2="716" />
                      <line x1="500" y1="500" x2="923" y2="1082" />
                      <line x1="500" y1="500" x2="500" y2="1190" />
                      <line x1="500" y1="500" x2="71" y2="1091" />
                      <line x1="500" y1="500" x2="-166" y2="716" />
                      <line x1="500" y1="500" x2="-175" y2="281" />
                      <line x1="500" y1="500" x2="88" y2="-66" />
                      <line x1="500" y1="500" x2="500" y2="-240" />
                      <line x1="500" y1="500" x2="923" y2="-82" />
                      <line x1="500" y1="500" x2="1156" y2="287" />
                    </g>
                    <g fill={isLight ? "#1D4ED8" : "#F59E0B"}>
                      <circle cx="1166" cy="716" r="8" />
                      <circle cx="923" cy="1082" r="7" />
                      <circle cx="500" cy="1190" r="9" />
                      <circle cx="71" cy="1091" r="7" />
                      <circle cx="-166" cy="716" r="8" />
                      <circle cx="-175" cy="281" r="7" />
                      <circle cx="88" cy="-66" r="8" />
                      <circle cx="500" cy="-240" r="10" />
                      <circle cx="923" cy="-82" r="7" />
                      <circle cx="1156" cy="287" r="8" />
                    </g>
                    <text x="500" y="-290" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="26" letterSpacing="6" fill={isLight ? "#B45309" : "#C08B33"}>NATIONAL CYBER GRID · 28 STATES</text>
                  </g>

                  {/* Layer 7: I4C Command Operations */}
                  <g opacity={layers.L7}>
                    <ellipse cx="500" cy="500" rx="618" ry="268" fill="none" stroke={isLight ? "rgba(59,130,246,.3)" : "rgba(6,182,212,.3)"} strokeWidth="2" strokeDasharray="18 12" />
                    <ellipse cx="500" cy="500" rx="566" ry="228" fill="none" stroke={isLight ? "rgba(59,130,246,.14)" : "rgba(6,182,212,.14)"} strokeWidth="1.5" />
                    <g fill={isLight ? "rgba(59,130,246,.09)" : "rgba(6,182,212,.09)"} stroke={isLight ? "rgba(59,130,246,.38)" : "rgba(6,182,212,.38)"} strokeWidth="1.5">
                      <rect x="-96" y="404" width="120" height="70" rx="6" />
                      <rect x="976" y="404" width="120" height="70" rx="6" />
                    </g>
                    <g fill={isLight ? "rgba(18,58,99,.32)" : "rgba(231,233,236,.32)"}>
                      <circle cx="320" cy="742" r="14" />
                      <circle cx="500" cy="762" r="14" />
                      <circle cx="680" cy="742" r="14" />
                    </g>
                    <text x="500" y="-130" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="24" letterSpacing="6" fill={isLight ? "#2E86C8" : "#5BA9B8"}>I4C COMMAND OPERATIONS</text>
                  </g>

                  {/* Layer 6: Statutory Dossier Engine */}
                  <g opacity={layers.L6}>
                    <g fill={isLight ? "rgba(11,95,165,.06)" : "rgba(16,185,129,.06)"} stroke={isLight ? "rgba(11,95,165,.28)" : "rgba(16,185,129,.28)"} strokeWidth="1.5">
                      <rect x="96" y="120" width="210" height="104" rx="10" />
                      <rect x="694" y="120" width="210" height="104" rx="10" />
                      <rect x="96" y="776" width="210" height="104" rx="10" />
                      <rect x="694" y="776" width="210" height="104" rx="10" />
                    </g>
                    <g fontFamily="'JetBrains Mono',monospace" fontSize="17" fill={isLight ? "#2E86C8" : "#8FD9BC"} letterSpacing="1">
                      <text x="201" y="162" textAnchor="middle">SEC 91 CrPC</text>
                      <text x="201" y="192" textAnchor="middle" fill={isLight ? "#7A8FA6" : "#6B7480"}>PRESERVATION NOTICE</text>
                      <text x="799" y="162" textAnchor="middle">BNSS 94</text>
                      <text x="799" y="192" textAnchor="middle" fill={isLight ? "#7A8FA6" : "#6B7480"}>FREEZE ORDER</text>
                      <text x="201" y="818" textAnchor="middle">NCRP CASE FILE</text>
                      <text x="201" y="848" textAnchor="middle" fill={isLight ? "#7A8FA6" : "#6B7480"}>ACK 2026/DL/41822</text>
                      <text x="799" y="818" textAnchor="middle">HASH CERTIFICATE</text>
                      <text x="799" y="848" textAnchor="middle" fill={isLight ? "#7A8FA6" : "#6B7480"}>SHA-256 SIGNED</text>
                    </g>
                    <text x="500" y="946" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="20" letterSpacing="5" fill={isLight ? "#1E6FB8" : "#6EE7B7"}>STATUTORY DOSSIER ENGINE</text>
                  </g>

                  {/* Layer 5: VASP Cluster Identified */}
                  <g opacity={layers.L5}>
                    <circle cx="500" cy="500" r="412" fill="none" stroke={isLight ? "rgba(11,95,165,.55)" : "rgba(16,185,129,.55)"} strokeWidth="20" strokeDasharray="3 62" />
                    <circle cx="500" cy="500" r="430" fill="none" stroke={isLight ? "rgba(11,95,165,.28)" : "rgba(16,185,129,.28)"} strokeWidth="1.5" />
                    <rect x="352" y="58" width="296" height="36" rx="8" fill={isLight ? "rgba(11,95,165,.12)" : "rgba(16,185,129,.12)"} stroke={isLight ? "rgba(11,95,165,.5)" : "rgba(16,185,129,.5)"} strokeWidth="1.5" />
                    <text x="500" y="83" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="18" letterSpacing="2" fill={isLight ? "#2E86C8" : "#A7F3D0"}>VASP CLUSTER IDENTIFIED</text>
                  </g>

                  {/* Layer 4: Multi-Hop Traversal Graph Trace */}
                  <g opacity={layers.L4}>
                    <polyline points="188,417 424,293 698,302 640,581 456,751 723,430" fill="none" stroke={isLight ? "#C6D4E4" : "#242B33"} strokeWidth="3" />
                    <polyline 
                      points="188,417 424,293 698,302 640,581 456,751 723,430" 
                      fill="none" 
                      stroke={isLight ? "#0B5FA5" : "#10B981"} 
                      strokeWidth="3.5" 
                      strokeLinejoin="round" 
                      strokeLinecap="round" 
                      pathLength="100" 
                      strokeDasharray="100" 
                      strokeDashoffset={dashOff} 
                      style={{ filter: isLight ? "drop-shadow(0 0 7px rgba(11,95,165,.55))" : "drop-shadow(0 0 8px rgba(16,185,129,.7))" }} 
                    />
                    <polyline points="188,417 424,293 698,302 640,581 456,751 723,430" fill="none" stroke="rgba(110,231,183,.55)" strokeWidth="1" strokeDasharray="6 18" style={{ animation: "flow 1.6s linear infinite" }} />

                    {/* Node 0: Reported */}
                    <circle cx="188" cy="417" r="23" fill={isLight ? "#FFFFFF" : "#0B0D10"} stroke={isLight ? "#CBD5E1" : "#2C333B"} strokeWidth="1.5" />
                    <circle cx="188" cy="417" r="8" fill={nodeColors.c0} />
                    <circle cx="188" cy="417" r="23" fill="none" stroke={nodeColors.c0} strokeWidth="1.5" opacity={nodeOpacities.o0} />
                    <text x="188" y="374" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="17" letterSpacing="2" fill={textColors.t0}>REPORTED</text>
                    <text x="188" y="345" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="14" fill={isLight ? "#64748B" : "#8E959E"}>0x7b51…ped1</text>

                    {/* Node 1: Hop 01 Peel */}
                    <circle cx="424" cy="293" r="19" fill={isLight ? "#FFFFFF" : "#0B0D10"} stroke={isLight ? "#CBD5E1" : "#2C333B"} strokeWidth="1.5" />
                    <circle cx="424" cy="293" r="6.5" fill={nodeColors.c1} />
                    <circle cx="424" cy="293" r="19" fill="none" stroke={nodeColors.c1} strokeWidth="1.5" opacity={nodeOpacities.o1} />
                    <text x="424" y="256" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="15" letterSpacing="2" fill={textColors.t1}>HOP 01 PEEL</text>

                    {/* Node 2: Hop 02 Mixer */}
                    <circle cx="698" cy="302" r="19" fill={isLight ? "#FFFFFF" : "#0B0D10"} stroke={isLight ? "#CBD5E1" : "#2C333B"} strokeWidth="1.5" />
                    <circle cx="698" cy="302" r="6.5" fill={nodeColors.c2} />
                    <circle cx="698" cy="302" r="19" fill="none" stroke={nodeColors.c2} strokeWidth="1.5" opacity={nodeOpacities.o2} />
                    <text x="698" y="265" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="15" letterSpacing="2" fill={textColors.t2}>HOP 02 MIXER</text>

                    {/* Node 3: Hop 03 Bridge */}
                    <circle cx="640" cy="581" r="19" fill={isLight ? "#FFFFFF" : "#0B0D10"} stroke={isLight ? "#CBD5E1" : "#2C333B"} strokeWidth="1.5" />
                    <circle cx="640" cy="581" r="6.5" fill={nodeColors.c3} />
                    <circle cx="640" cy="581" r="19" fill="none" stroke={nodeColors.c3} strokeWidth="1.5" opacity={nodeOpacities.o3} />
                    <text x="640" y="622" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="15" letterSpacing="2" fill={textColors.t3}>HOP 03 BRIDGE</text>

                    {/* Node 4: Hop 04 Mule */}
                    <circle cx="456" cy="751" r="19" fill={isLight ? "#FFFFFF" : "#0B0D10"} stroke={isLight ? "#CBD5E1" : "#2C333B"} strokeWidth="1.5" />
                    <circle cx="456" cy="751" r="6.5" fill={nodeColors.c4} />
                    <circle cx="456" cy="751" r="19" fill="none" stroke={nodeColors.c4} strokeWidth="1.5" opacity={nodeOpacities.o4} />
                    <text x="456" y="792" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="15" letterSpacing="2" fill={textColors.t4}>HOP 04 MULE ×14</text>

                    {/* Node 5: Hot Wallet 4 */}
                    <circle cx="723" cy="430" r="26" fill={isLight ? "#FFFFFF" : "#0B0D10"} stroke={nodeColors.c5} strokeWidth="2" />
                    <circle cx="723" cy="430" r="9" fill={nodeColors.c5} />
                    <circle cx="723" cy="430" r="26" fill="none" stroke={nodeColors.c5} strokeWidth="2" opacity={nodeOpacities.o5} style={{ animation: "ping 2.2s ease-out infinite", transformOrigin: "723px 430px" }} />
                    <text x="723" y="484" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="16" letterSpacing="2" fill={textColors.t5}>HOT WALLET 4</text>

                    {/* Traveling Light Indicator */}
                    <circle cx={dotX} cy={dotY} r="18" fill={isLight ? "rgba(11,95,165,.16)" : "rgba(16,185,129,.16)"} />
                    <circle cx={dotX} cy={dotY} r={7} fill={isLight ? "#059669" : "#ECFDF5"} style={{ filter: "drop-shadow(0 0 10px #10B981)" }} />
                  </g>

                  {/* Layer 3: Mixer / Bridge Traversal */}
                  <g opacity={layers.L3}>
                    <g style={{ animation: "sweep 16s linear infinite", transformOrigin: "500px 500px" }}>
                      <ellipse cx="500" cy="500" rx="238" ry="104" fill="none" stroke={isLight ? "rgba(59,130,246,.5)" : "rgba(6,182,212,.5)"} strokeWidth="2" strokeDasharray="14 10" />
                      <ellipse cx="500" cy="500" rx="238" ry="104" fill="none" stroke={isLight ? "rgba(59,130,246,.34)" : "rgba(6,182,212,.34)"} strokeWidth="2" transform="rotate(60 500 500)" />
                      <ellipse cx="500" cy="500" rx="238" ry="104" fill="none" stroke={isLight ? "rgba(59,130,246,.34)" : "rgba(6,182,212,.34)"} strokeWidth="2" transform="rotate(120 500 500)" />
                    </g>
                    <text x="500" y="748" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="16" letterSpacing="4" fill={isLight ? "#2E86C8" : "#5BA9B8"}>MIXER / BRIDGE TRAVERSAL</text>
                  </g>

                  {/* Layer 2: Peel Chain Burners */}
                  <g opacity={layers.L2}>
                    <g stroke={isLight ? "rgba(11,95,165,.55)" : "rgba(16,185,129,.55)"} strokeWidth="2">
                      <line x1="572" y1="500" x2="650" y2="500" />
                      <line x1="551" y1="551" x2="606" y2="606" />
                      <line x1="500" y1="572" x2="500" y2="650" />
                      <line x1="449" y1="551" x2="394" y2="606" />
                      <line x1="428" y1="500" x2="350" y2="500" />
                      <line x1="449" y1="449" x2="394" y2="394" />
                      <line x1="500" y1="428" x2="500" y2="350" />
                      <line x1="551" y1="449" x2="606" y2="394" />
                    </g>
                    <g fill={isLight ? "#0B5FA5" : "#10B981"}>
                      <circle cx="650" cy="500" r="7" />
                      <circle cx="606" cy="606" r="6" />
                      <circle cx="500" cy="650" r="7" />
                      <circle cx="394" cy="606" r="6" />
                      <circle cx="350" cy="500" r="7" />
                      <circle cx="394" cy="394" r="6" />
                      <circle cx="500" cy="350" r="7" fill={isLight ? "#1D4ED8" : "#F59E0B"} />
                      <circle cx="606" cy="394" r="6" />
                    </g>
                    <g stroke={isLight ? "rgba(11,95,165,.4)" : "rgba(16,185,129,.4)"} strokeWidth="1.5">
                      <line x1="500" y1="500" x2="424" y2="293" />
                      <line x1="500" y1="500" x2="576" y2="293" />
                      <line x1="500" y1="500" x2="620" y2="400" />
                      <line x1="500" y1="500" x2="380" y2="400" />
                    </g>
                    <circle cx="500" cy="500" r="118" fill="none" stroke={isLight ? "rgba(11,95,165,.35)" : "rgba(16,185,129,.35)"} strokeWidth="1.5" strokeDasharray="6 8" />
                  </g>

                  {/* Layer 1: Compromised Seed & Victim Breach */}
                  <g opacity={layers.L1}>
                    <circle cx="500" cy="500" r="54" fill="none" stroke="rgba(239,68,68,.5)" strokeWidth="1.5" strokeDasharray="2 9" />
                    <circle cx="500" cy="500" r="70" fill="none" stroke={isLight ? "rgba(29,78,216,.22)" : "rgba(245,158,11,.22)"} strokeWidth="1" />
                    <g style={{ animation: "sweep 7s linear infinite", transformOrigin: "500px 500px" }}>
                      <circle cx="562" cy="500" r="2.6" fill={isLight ? "#1D4ED8" : "#F59E0B"} />
                      <circle cx="500" cy="438" r="2.2" fill={isLight ? "#D6002A" : "#EF4444"} />
                    </g>
                    <text x="500" y="506" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="15" letterSpacing="1" fill={isLight ? "#1D4ED8" : "#F59E0B"}>0x7b51…ped1</text>
                    <text x="500" y="459" textAnchor="middle" fontFamily="'JetBrains Mono',monospace" fontSize="9" letterSpacing="2" fill={isLight ? "#B45309" : "#A0763A"}>BREACH POINT</text>
                  </g>
                </g>
              </svg>
            </div>
          )}

          {/* ── Left Hero Copy ── */}
          <div 
            className="transform-gpu will-change-transform"
            style={{ 
              gridRow: 2, 
              gridColumn: "1 / -1", 
              minWidth: 0, 
              minHeight: 0, 
              overflow: "hidden", 
              position: "relative", 
              zIndex: 5, 
              display: "flex", 
              flexDirection: "column", 
              alignItems: "center",
              textAlign: "center",
              justifyContent: "center", 
              maxWidth: "min(1000px, 92vw)",
              margin: "0 auto",
              padding: "0 clamp(16px,3vw,40px)",
              willChange: "transform",
              transform: "translate3d(0, 0, 0)"
            }}
          >
            <div
              aria-hidden="true"
              style={{
                position: "absolute",
                inset: "-8% -10%",
                zIndex: -1,
                pointerEvents: "none",
                background: isLight
                  ? "radial-gradient(48% 44% at 50% 48%, rgba(248,251,255,.97) 0%, rgba(248,251,255,.88) 38%, rgba(248,251,255,0) 72%)"
                  : "radial-gradient(48% 44% at 50% 48%, rgba(6,10,9,.94) 0%, rgba(6,10,9,.8) 38%, rgba(6,10,9,0) 72%)",
              }}
            />

            <div style={{ display: "inline-flex", alignSelf: "center", alignItems: "center", gap: "8px", padding: "6px 14px", border: isLight ? "1px solid rgba(245,158,11,.45)" : "1px solid rgba(245,158,11,.35)", background: isLight ? "rgba(245,158,11,.14)" : "rgba(245,158,11,.07)", borderRadius: "999px", marginBottom: "clamp(10px,2.2vh,26px)" }}>
              <span style={{ width: "6px", height: "6px", borderRadius: "999px", background: "#F59E0B", boxShadow: "0 0 8px #F59E0B" }} />
              <span style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: "9.5px", letterSpacing: ".14em", color: isLight ? "#B45309" : "#FCD34D", fontWeight: 700 }}>NCRP &amp; SAHYOG PLATFORM INTEGRATED</span>
            </div>

            <h1 style={{ margin: 0, fontSize: "clamp(28px,min(7.2vw,5.6vh),60px)", lineHeight: 1.04, letterSpacing: "-.02em", fontWeight: 600, color: isLight ? "#0F2440" : "#FFFFFF", textShadow: isLight ? "0 0 26px rgba(244,247,251,.95), 0 1px 2px rgba(255,255,255,.9)" : "0 0 34px rgba(0,0,0,.85), 0 0 12px rgba(0,0,0,.9), 0 0 56px rgba(110,231,183,.3)" }}>
              From a reported wallet to the exchange holding the funds — <span style={{ color: isLight ? "#0B5FA5" : "#6EE7B7", textShadow: isLight ? "0 0 26px rgba(244,247,251,.95)" : "0 0 30px rgba(110,231,183,.5), 0 0 10px rgba(0,0,0,.85)" }}>traced automatically.</span>
            </h1>

            <p style={{ margin: "clamp(12px,2.4vh,24px) 0 0", fontSize: "clamp(14px,min(3.6vw,1.15vw + 8px),17px)", lineHeight: 1.55, color: isLight ? "#3A5570" : "#C2C8D0", textShadow: isLight ? "0 0 18px rgba(244,247,251,.95)" : "0 0 20px rgba(0,0,0,.9), 0 0 8px rgba(0,0,0,.85)" }}>
              Report a suspect address. Chakravyuh follows the funds across chains, mixers, and intermediary mules to pinpoint the destination VASP in minutes, not weeks.
            </p>

            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "12px", marginTop: "clamp(16px,3.2vh,34px)" }}>
              <button 
                type="button" 
                onClick={() => navigate("/dashboard")}
                className="rolex-gold-btn"
                style={{ fontFamily: "Archivo, sans-serif", fontSize: "14px", padding: "13px 26px", borderRadius: "12px", cursor: "pointer" }}
              >
                Open Investigation Dashboard ↗
              </button>
              <button 
                type="button" 
                onClick={() => scrollToSection("how-it-works")}
                style={{ background: isLight ? "rgba(255,255,255,0.9)" : "rgba(24,24,27,.5)", border: isLight ? "1px solid #CBD5E1" : "1px solid rgba(63,63,70,.9)", color: isLight ? "#334155" : "#D4D8DE", fontFamily: "Archivo, sans-serif", fontSize: "14px", padding: "12px 20px", borderRadius: "10px", cursor: "pointer", backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)", transition: "all 0.2s" }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = "#10B981"; e.currentTarget.style.color = "#059669"; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = isLight ? "#CBD5E1" : "rgba(63,63,70,.9)"; e.currentTarget.style.color = isLight ? "#334155" : "#D4D8DE"; }}
              >
                How the tracing works
              </button>
            </div>

            <div style={{ marginTop: "clamp(12px,2.4vh,30px)", fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: "10.5px", letterSpacing: ".1em", color: isLight ? "#0B5FA5" : "#10B981", display: "flex", alignItems: "center", justifyContent: "center", gap: "9px" }}>
              <span style={{ width: "6px", height: "6px", background: "#10B981", borderRadius: "999px", animation: "blink 1.2s infinite" }} />
              <span>{phase}</span>
            </div>
          </div>

          {/* Clean hero bottom with no progress bar line */}
        </section>
      </div>

      {/* ── Section: Active Ingestion Stream & Evidence Dossier ── */}
      <section 
        id="evidence" 
        className="transform-gpu will-change-transform will-change-opacity"
        style={{ 
          position: "relative", 
          zIndex: 10, 
          background: "transparent", 
          borderTop: isLight ? "1px solid rgba(226,232,240,.9)" : "1px solid rgba(39,39,42,.7)", 
          padding: "clamp(56px,9vh,110px) clamp(16px,3vw,40px)", 
          transition: "background 0.3s",
          willChange: "transform, opacity",
          transform: "translate3d(0, 0, 0)"
        }}
      >
        <div style={{ maxWidth: "min(1760px, 94vw)", margin: "0 auto" }}>
          <motion.div 
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ type: "spring", stiffness: 80, damping: 20, mass: 0.1 }}
            style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "18px", justifyContent: "space-between" }}
          >
            <div>
              <div style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: "9.5px", letterSpacing: ".18em", color: isLight ? "#059669" : "#10B981", fontWeight: 700 }}>ACTIVE INGESTION STREAM</div>
              <h2 style={{ margin: "14px 0 0", fontSize: "clamp(21px,5.2vw,38px)", fontWeight: 600, letterSpacing: "-.015em", color: isLight ? "#0F172A" : "#FFFFFF" }}>Active suspects under trace</h2>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <button
                type="button"
                onClick={() => navigate("/dashboard")}
                style={{ display: "inline-flex", alignItems: "center", gap: "6px", background: isLight ? "rgba(16,185,129,.14)" : "rgba(16,185,129,.1)", border: isLight ? "1px solid rgba(16,185,129,.4)" : "1px solid rgba(16,185,129,.3)", color: isLight ? "#059669" : "#6EE7B7", fontFamily: "'JetBrains Mono', monospace", fontSize: "11px", fontWeight: 600, padding: "7px 14px", borderRadius: "8px", cursor: "pointer" }}
              >
                <Database size={13} />
                <span>Open Full Evidence Ledger (49 Hops) →</span>
              </button>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "7px 13px", border: isLight ? "1px solid rgba(16,185,129,.4)" : "1px solid rgba(16,185,129,.35)", background: isLight ? "rgba(16,185,129,.1)" : "rgba(16,185,129,.07)", borderRadius: "999px" }}>
                <span style={{ width: "6px", height: "6px", borderRadius: "999px", background: "#10B981", boxShadow: "0 0 8px #10B981", animation: "blink 1.5s infinite" }} />
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "9.5px", letterSpacing: ".12em", color: isLight ? "#059669" : "#6EE7B7", fontWeight: 700 }}>SWEEP BOT · 4 ALERTS</span>
              </div>
            </div>
          </motion.div>

          <motion.div 
            initial={{ opacity: 0, y: 35 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-40px" }}
            transition={{ type: "spring", stiffness: 85, damping: 22, mass: 0.12, delay: 0.1 }}
            className="transform-gpu will-change-transform"
            style={{ 
              marginTop: "32px", 
              backdropFilter: "blur(12px)", 
              WebkitBackdropFilter: "blur(12px)", 
              background: isLight ? "rgba(255,255,255,.98)" : "rgba(9,9,11,.8)", 
              border: isLight ? "1px solid rgba(203,213,225,.9)" : "1px solid rgba(16,185,129,.2)", 
              borderRadius: "16px", 
              overflow: "hidden", 
              boxShadow: isLight ? "0 10px 30px rgba(0,0,0,0.06)" : "none",
              willChange: "transform",
              transform: "translate3d(0, 0, 0)",
              backfaceVisibility: "hidden",
              WebkitBackfaceVisibility: "hidden"
            }}
          >
            <div className="stream-grid stream-grid--head" style={{ display: "grid", gridTemplateColumns: "minmax(92px,.8fr) minmax(140px,1.3fr) minmax(86px,.8fr) minmax(120px,1fr) minmax(56px,.5fr) minmax(120px,1fr)", gap: "10px", padding: "14px 20px", borderBottom: isLight ? "1px solid rgba(226,232,240,.9)" : "1px solid rgba(39,39,42,.9)", fontFamily: "'JetBrains Mono', monospace", fontSize: "9px", letterSpacing: ".14em", color: isLight ? "#64748B" : "#6B7480", background: isLight ? "rgba(241,245,249,.8)" : "rgba(8,9,12,.5)" }}>
              <div>COMPLAINT</div><div>SUSPECT WALLET</div><div>TRACED VOL.</div><div>RISK SCORE</div><div>HOPS</div><div>TARGET VASP</div>
            </div>

            {/* Row 1 */}
            <div 
              onClick={() => navigateToDashboardWithWallet("0x7b51e041289cf30114041b63e6358ped1")}
              className="stream-grid"
              style={{ display: "grid", gridTemplateColumns: "minmax(92px,.8fr) minmax(140px,1.3fr) minmax(86px,.8fr) minmax(120px,1fr) minmax(56px,.5fr) minmax(120px,1fr)", gap: "10px", padding: "16px 20px", borderBottom: isLight ? "1px solid rgba(226,232,240,.8)" : "1px solid rgba(39,39,42,.6)", fontFamily: "'JetBrains Mono', monospace", fontSize: "11.5px", alignItems: "center", color: isLight ? "#0F172A" : "#D4D8DE", cursor: "pointer", transition: "background 0.15s" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = isLight ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.04)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ color: isLight ? "#64748B" : "#9BA1AA" }}>DL/41822</div>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", color: isLight ? "#059669" : "#6EE7B7", fontWeight: 700 }}>0x7b51…ped1 ↗</div>
              <div style={{ fontWeight: 600 }}>412.5 USDT</div>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "7px" }}><span style={{ color: "#F59E0B", fontWeight: 700 }}>86/100</span><span style={{ fontSize: "9px", letterSpacing: ".1em", color: "#F59E0B" }}>HIGH</span></div>
                <svg width="100%" height="3" preserveAspectRatio="none" style={{ display: "block", marginTop: "6px" }}><rect width="100%" height="3" rx="1.5" fill={isLight ? "#E2E8F0" : "#1C2228"} /><rect width="86%" height="3" rx="1.5" fill="#F59E0B" /></svg>
              </div>
              <div style={{ fontWeight: 600 }}>05</div>
              <div style={{ color: "#F59E0B", display: "flex", alignItems: "center", gap: "6px", fontWeight: 600 }}><span style={{ width: "5px", height: "5px", borderRadius: "999px", background: "#F59E0B", animation: "blink 1.4s infinite", flex: "none" }} />FREEZE SENT</div>
            </div>

            {/* Row 2 */}
            <div 
              onClick={() => navigateToDashboardWithWallet("TXmc9K81Lp9nQ2xM4vB6rT98Z1kLp9q4Kqa")}
              className="stream-grid"
              style={{ display: "grid", gridTemplateColumns: "minmax(92px,.8fr) minmax(140px,1.3fr) minmax(86px,.8fr) minmax(120px,1fr) minmax(56px,.5fr) minmax(120px,1fr)", gap: "10px", padding: "16px 20px", borderBottom: isLight ? "1px solid rgba(226,232,240,.8)" : "1px solid rgba(39,39,42,.6)", fontFamily: "'JetBrains Mono', monospace", fontSize: "11.5px", alignItems: "center", color: isLight ? "#0F172A" : "#D4D8DE", cursor: "pointer", transition: "background 0.15s" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = isLight ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.04)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ color: isLight ? "#64748B" : "#9BA1AA" }}>MH/09117</div>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", color: isLight ? "#059669" : "#6EE7B7", fontWeight: 700 }}>TXmc9…4Kqa ↗</div>
              <div style={{ fontWeight: 600 }}>1,204.0 USDT</div>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "7px" }}><span style={{ color: "#EF4444", fontWeight: 700 }}>95/100</span><span style={{ fontSize: "9px", letterSpacing: ".1em", color: "#EF4444" }}>CRITICAL</span></div>
                <svg width="100%" height="3" preserveAspectRatio="none" style={{ display: "block", marginTop: "6px" }}><rect width="100%" height="3" rx="1.5" fill={isLight ? "#E2E8F0" : "#1C2228"} /><rect width="95%" height="3" rx="1.5" fill="#EF4444" /></svg>
              </div>
              <div style={{ fontWeight: 600 }}>09</div>
              <div style={{ color: isLight ? "#059669" : "#6EE7B7", display: "flex", alignItems: "center", gap: "6px", fontWeight: 600 }}><span style={{ width: "5px", height: "5px", borderRadius: "999px", background: "#10B981", flex: "none" }} />TIER-1 CEX</div>
            </div>

            {/* Row 3 */}
            <div 
              onClick={() => navigateToDashboardWithWallet("0x31af89cf30114041b63e6358ped1c07e")}
              className="stream-grid"
              style={{ display: "grid", gridTemplateColumns: "minmax(92px,.8fr) minmax(140px,1.3fr) minmax(86px,.8fr) minmax(120px,1fr) minmax(56px,.5fr) minmax(120px,1fr)", gap: "10px", padding: "16px 20px", borderBottom: isLight ? "1px solid rgba(226,232,240,.8)" : "1px solid rgba(39,39,42,.6)", fontFamily: "'JetBrains Mono', monospace", fontSize: "11.5px", alignItems: "center", color: isLight ? "#0F172A" : "#D4D8DE", cursor: "pointer", transition: "background 0.15s" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = isLight ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.04)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ color: isLight ? "#64748B" : "#9BA1AA" }}>KA/22540</div>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", color: isLight ? "#059669" : "#6EE7B7", fontWeight: 700 }}>0x31af…c07e ↗</div>
              <div style={{ fontWeight: 600 }}>88.2 USDT</div>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "7px" }}><span style={{ color: isLight ? "#059669" : "#6EE7B7", fontWeight: 700 }}>42/100</span><span style={{ fontSize: "9px", letterSpacing: ".1em", color: isLight ? "#059669" : "#6EE7B7" }}>MODERATE</span></div>
                <svg width="100%" height="3" preserveAspectRatio="none" style={{ display: "block", marginTop: "6px" }}><rect width="100%" height="3" rx="1.5" fill={isLight ? "#E2E8F0" : "#1C2228"} /><rect width="42%" height="3" rx="1.5" fill="#10B981" /></svg>
              </div>
              <div style={{ fontWeight: 600 }}>03</div>
              <div style={{ color: isLight ? "#64748B" : "#9BA1AA", display: "flex", alignItems: "center", gap: "6px" }}><span style={{ width: "5px", height: "5px", borderRadius: "999px", background: "#64748B", flex: "none" }} />UNRESOLVED</div>
            </div>

            {/* Row 4 */}
            <div 
              onClick={() => navigateToDashboardWithWallet("bc1qy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh")}
              className="stream-grid"
              style={{ display: "grid", gridTemplateColumns: "minmax(92px,.8fr) minmax(140px,1.3fr) minmax(86px,.8fr) minmax(120px,1fr) minmax(56px,.5fr) minmax(120px,1fr)", gap: "10px", padding: "16px 20px", fontFamily: "'JetBrains Mono', monospace", fontSize: "11.5px", alignItems: "center", color: isLight ? "#0F172A" : "#D4D8DE", cursor: "pointer", transition: "background 0.15s" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = isLight ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.04)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ color: isLight ? "#64748B" : "#9BA1AA" }}>WB/70318</div>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", color: isLight ? "#059669" : "#6EE7B7", fontWeight: 700 }}>bc1qy…7f2d ↗</div>
              <div style={{ fontWeight: 600 }}>2.41 BTC</div>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "7px" }}><span style={{ color: "#F59E0B", fontWeight: 700 }}>78/100</span><span style={{ fontSize: "9px", letterSpacing: ".1em", color: "#F59E0B" }}>HIGH</span></div>
                <svg width="100%" height="3" preserveAspectRatio="none" style={{ display: "block", marginTop: "6px" }}><rect width="100%" height="3" rx="1.5" fill={isLight ? "#E2E8F0" : "#1C2228"} /><rect width="78%" height="3" rx="1.5" fill="#F59E0B" /></svg>
              </div>
              <div style={{ fontWeight: 600 }}>06</div>
              <div style={{ color: "#F59E0B", display: "flex", alignItems: "center", gap: "6px", fontWeight: 600 }}><span style={{ width: "5px", height: "5px", borderRadius: "999px", background: "#F59E0B", animation: "blink 1.4s infinite", flex: "none" }} />SWEEP DETECTED</div>
            </div>
          </motion.div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "14px", alignItems: "center", justifyContent: "space-between", marginTop: "26px", fontFamily: "'JetBrains Mono', monospace", fontSize: "10px", letterSpacing: ".12em", color: isLight ? "#64748B" : "#6B7480" }}>
            <div>PROBLEM STATEMENT ID 26183 · MHA / I4C</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "20px" }}>
              <span>CHAIN COVERAGE: 11</span>
              <span>MEDIAN ATTRIBUTION: 3M 52S</span>
              <span>EVIDENCE HASH: SHA-256</span>
            </div>
          </div>

          {/* ── Ready to Trace CTA Banner ── */}
          <motion.div 
            initial={{ opacity: 0, y: 35 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-40px" }}
            transition={{ type: "spring", stiffness: 85, damping: 22, mass: 0.12 }}
            className="transform-gpu will-change-transform"
            style={{ 
              marginTop: "48px", 
              borderRadius: "20px", 
              border: isLight ? "1px solid rgba(16,185,129,.4)" : "1px solid rgba(16,185,129,.3)", 
              background: isLight ? "linear-gradient(135deg, rgba(16,185,129,.15) 0%, rgba(255,255,255,.98) 100%)" : "linear-gradient(135deg, rgba(16,185,129,.12) 0%, rgba(8,9,12,.95) 100%)", 
              padding: "36px clamp(20px,4vw,48px)", 
              display: "flex", 
              flexWrap: "wrap", 
              alignItems: "center", 
              justifyContent: "space-between", 
              gap: "24px", 
              boxShadow: isLight ? "0 14px 40px rgba(16,185,129,0.08)" : "none",
              willChange: "transform",
              transform: "translate3d(0, 0, 0)",
              backfaceVisibility: "hidden",
              WebkitBackfaceVisibility: "hidden"
            }}
          >
            <div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "10px", letterSpacing: ".15em", color: isLight ? "#059669" : "#6EE7B7", fontWeight: 700 }}>NATIONAL CYBERCRIME THREAT INTELLIGENCE</div>
              <h3 style={{ margin: "8px 0 0", fontSize: "clamp(19px,4.6vw,28px)", fontWeight: 700, color: isLight ? "#0F172A" : "#fff" }}>Ready to initiate autonomous on-chain attribution?</h3>
              <p style={{ margin: "8px 0 0", fontSize: "14px", color: isLight ? "#475569" : "#9BA1AA", maxWidth: "60ch" }}>
                Ingest victim complaint addresses directly into the multi-hop graph engine and issue court-certified Section 91 notices in seconds.
              </p>
            </div>
            <button
              type="button"
              onClick={() => navigate("/dashboard")}
              className="rolex-gold-btn"
              style={{ fontFamily: "Archivo, sans-serif", fontSize: "14px", padding: "14px 28px", borderRadius: "14px", cursor: "pointer" }}
            >
              Launch Live Attribution Workbench ↗
            </button>
          </motion.div>
        </div>
      </section>

      {/* ── Section: How the tracing works ── */}
      <section
        id="how-it-works"
        style={{
          position: "relative",
          zIndex: 10,
          background: "transparent",
          borderTop: isLight ? "1px solid rgba(226,232,240,.9)" : "1px solid rgba(39,39,42,.7)",
        }}
      >
        <HowItWorksSection />
      </section>

      <BackToTop />

      {/* ── Footer ── */}
      <footer style={{ position: "relative", zIndex: 10, background: isLight ? "#FFFFFF" : "#08090C", borderTop: isLight ? "1px solid rgba(226,232,240,.9)" : "1px solid rgba(39,39,42,.7)", padding: "34px clamp(16px,3vw,40px)", display: "flex", flexWrap: "wrap", gap: "14px", justifyContent: "space-between", alignItems: "center", fontFamily: "'JetBrains Mono', monospace", fontSize: "10px", letterSpacing: ".12em", color: isLight ? "#64748B" : "#4E555E" }}>
        <div>CHAKRAVYUH · SETU</div>
        <div>RESTRICTED — FOR AUTHORISED LAW ENFORCEMENT USE</div>
      </footer>
    </div>
  );
}

// Alias export for backward compatibility
export const SetuDashboard = LandingPage;
export default LandingPage;
