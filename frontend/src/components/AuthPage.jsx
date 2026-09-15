import React, { useState } from "react";
import { ArrowRight, BadgeCheck, Building, Eye, EyeOff, KeyRound, Lock, ShieldCheck, User } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import ChakravyuhLogo from "./ChakravyuhLogo.jsx";
import { useTheme } from "../lib/ThemeContext.jsx";
import { signInOfficer, signUpOfficer } from "../lib/auth.js";

const STATIONS = [
  "CYBER-PS-I4C-DELHI",
  "CID-CYBER-MUMBAI",
  "FIU-IND-NODAL-CELL",
  "STF-CYBER-BENGALURU",
];

export function AuthPage({ initialMode = "login" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const dest = location.state?.from ?? "/dashboard";
  const { theme } = useTheme();
  const [mode, setMode] = useState(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [badgeId, setBadgeId] = useState("");
  const [stationCode, setStationCode] = useState(STATIONS[0]);
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const isSignup = mode === "signup";

  async function handleAuth(e) {
    e?.preventDefault();
    setError(null);
    setNotice(null);
    setLoading(true);
    try {
      if (isSignup) {
        const data = await signUpOfficer({
          email,
          password,
          fullName,
          badgeId,
          stationCode,
          clearance: "Tier 1 - Unit Attribution",
        });
        if (data?.session) {
          window.location.href = dest;
          return;
        }
        setNotice("Account created. Sign in to continue.");
        setMode("login");
      } else {
        await signInOfficer({ email, password });
        window.location.href = dest;
      }
    } catch (err) {
      setError(err?.message ?? "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-split">
      {/* ── Form side ── */}
      <div className="auth-split__form">
        <button type="button" className="auth-brand" onClick={() => navigate("/")}>
          <ChakravyuhLogo />
        </button>

        <div className="auth-form-wrap">
          <h1 className="auth-title">{isSignup ? "Request agency access" : "Welcome back"}</h1>
          <p className="auth-sub">
            {isSignup
              ? "Provision a workspace for your cyber crime unit"
              : "Please enter your details"}
          </p>

          {(error || notice) && (
            <div className={`auth-banner ${error ? "is-error" : "is-ok"}`}>{error ?? notice}</div>
          )}

          <form onSubmit={handleAuth} className="auth-fields">
            {isSignup && (
              <>
                <label className="auth-field">
                  <span>Officer full name</span>
                  <div className="auth-input">
                    <User size={14} />
                    <input required value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Inspector A. Sharma" />
                  </div>
                </label>
                <div className="auth-row">
                  <label className="auth-field">
                    <span>Badge / service ID</span>
                    <div className="auth-input">
                      <BadgeCheck size={14} />
                      <input required value={badgeId} onChange={(e) => setBadgeId(e.target.value)} placeholder="I4C-IND-88219" />
                    </div>
                  </label>
                  <label className="auth-field">
                    <span>Station / unit</span>
                    <div className="auth-input">
                      <Building size={14} />
                      <select value={stationCode} onChange={(e) => setStationCode(e.target.value)}>
                        {STATIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </div>
                  </label>
                </div>
              </>
            )}

            <label className="auth-field">
              <span>Email address</span>
              <div className="auth-input">
                <User size={14} />
                <input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
              </div>
            </label>

            <label className="auth-field">
              <span>Password</span>
              <div className="auth-input">
                <Lock size={14} />
                <input
                  required
                  minLength={6}
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 6 characters"
                />
                <button type="button" className="auth-eye" onClick={() => setShowPassword(!showPassword)} aria-label="Toggle password">
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </label>

            {!isSignup && (
              <div className="auth-meta">
                <label className="auth-check">
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                  Remember for 30 days
                </label>
                <button type="button" className="auth-link" onClick={() => setNotice("Password reset is managed by the configured Supabase project.")}>
                  Forgot password
                </button>
              </div>
            )}

            <button type="submit" className="auth-submit" disabled={loading}>
              {loading ? "Verifying clearance…" : isSignup ? "Create account" : "Sign in"}
              {!loading && <ArrowRight size={15} />}
            </button>
          </form>


          <p className="auth-switch">
            {isSignup ? "Already provisioned?" : "Don't have an account?"}{" "}
            <button type="button" className="auth-link" onClick={() => { setMode(isSignup ? "login" : "signup"); setError(null); }}>
              {isSignup ? "Sign in" : "Request access"}
            </button>
          </p>
        </div>

        <p className="auth-foot">
          <KeyRound size={11} /> Official cyber forensics network · 256-bit encrypted
        </p>
      </div>

      {/* ── Brand side: the attribution loop, drawn in the product palette ── */}
      <aside className="auth-split__art" aria-hidden="true">
        <div className="auth-art-grid" />
        <div className="auth-art-sweep" />
        <svg viewBox="0 0 420 420" className="auth-art-svg">
          <defs>
            <linearGradient id="authEdge" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="var(--auth-accent)" stopOpacity=".9" />
              <stop offset="100%" stopColor="var(--auth-accent-2)" stopOpacity=".3" />
            </linearGradient>
          </defs>
          {[170, 130, 90].map((r, i) => (
            <circle key={r} cx="210" cy="210" r={r} fill="none" stroke="var(--auth-ring)" strokeWidth="1"
              strokeDasharray={i === 1 ? "4 10" : "none"} opacity={0.5 - i * 0.08} />
          ))}
          <polyline className="auth-art-path" points="70,250 150,150 250,180 300,96 350,210 260,300 140,290"
            fill="none" stroke="url(#authEdge)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          {[[70,250],[150,150],[250,180],[300,96],[350,210],[260,300],[140,290]].map(([x,y],i)=>(
            <circle key={i} cx={x} cy={y} r="6" className="auth-art-node" style={{ animationDelay: `${i*0.26}s` }} />
          ))}
          <circle r="5" className="auth-art-packet">
            <animateMotion dur="7s" repeatCount="indefinite"
              path="M70,250 L150,150 L250,180 L300,96 L350,210 L260,300 L140,290" />
          </circle>
        </svg>

        <div className="auth-art-copy">
          <h2>Every rupee has a route.</h2>
          <p>Chakravyuh walks it hop by hop, names the exchange at the end, and hands you the notice to send.</p>
          <div className="auth-art-tags">
            <span><ShieldCheck size={12} /> Sec 65B ready</span>
            <span>NCRP integrated</span>
          </div>
        </div>
      </aside>
    </div>
  );
}

export default AuthPage;
