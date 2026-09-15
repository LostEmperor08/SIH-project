import React, { useState } from "react";
import { ArrowRight, BadgeCheck, Building, Eye, EyeOff, KeyRound, Lock, ShieldCheck, User } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import ChakravyuhLogo from "./ChakravyuhLogo.jsx";
import { useTheme } from "../lib/ThemeContext.jsx";
import { signInOfficer, signUpOfficer, signInWithOAuthProvider } from "../lib/auth.js";

const STATIONS = [
  "CYBER-PS-I4C-DELHI",
  "CID-CYBER-MUMBAI",
  "FIU-IND-NODAL-CELL",
  "STF-CYBER-BENGALURU",
  "HQ-CYBER-SECURITY-CELL",
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
  const [oauthLoading, setOauthLoading] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const isSignup = mode === "signup";

  async function handleOAuth(provider) {
    setError(null);
    setNotice(null);
    setOauthLoading(provider);
    try {
      await signInWithOAuthProvider(provider);
    } catch (err) {
      setError(err?.message ?? `Failed to authenticate with ${provider}. Please verify Supabase OAuth provider settings.`);
      setOauthLoading(null);
    }
  }

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
        setNotice("Account created in Supabase. You can now sign in with your officer credentials.");
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
          <h1 className="auth-title">{isSignup ? "Create Officer Account" : "Officer Authentication"}</h1>
          <p className="auth-sub">
            {isSignup
              ? "Register an authorized cyber investigation account with Supabase"
              : "Sign in with your enterprise credentials or identity provider"}
          </p>

          {(error || notice) && (
            <div className={`auth-banner ${error ? "is-error" : "is-ok"}`}>{error ?? notice}</div>
          )}

          {/* ── OAuth Identity Providers ── */}
          <div className="auth-oauth-group">
            <button
              type="button"
              className="auth-oauth-btn auth-oauth-btn--google"
              onClick={() => handleOAuth("google")}
              disabled={loading || oauthLoading !== null}
            >
              <svg className="auth-oauth-icon" viewBox="0 0 24 24" width="18" height="18">
                <path
                  fill="#4285F4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                />
                <path
                  fill="#EA4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                />
              </svg>
              <span>{oauthLoading === "google" ? "Connecting to Google…" : "Continue with Google"}</span>
            </button>

            <button
              type="button"
              className="auth-oauth-btn auth-oauth-btn--microsoft"
              onClick={() => handleOAuth("azure")}
              disabled={loading || oauthLoading !== null}
            >
              <svg className="auth-oauth-icon" viewBox="0 0 23 23" width="18" height="18">
                <path fill="#f35325" d="M1 1h10v10H1z" />
                <path fill="#81bc06" d="M12 1h10v10H12z" />
                <path fill="#05a6f0" d="M1 12h10v10H1z" />
                <path fill="#ffba08" d="M12 12h10v10H12z" />
              </svg>
              <span>{oauthLoading === "azure" ? "Connecting to Microsoft…" : "Continue with Microsoft"}</span>
            </button>
          </div>

          <div className="auth-divider">
            <span>OR CONTINUE WITH CREDENTIALS</span>
          </div>

          <form onSubmit={handleAuth} className="auth-fields">
            {isSignup && (
              <>
                <label className="auth-field">
                  <span>Officer full name</span>
                  <div className="auth-input">
                    <User size={14} />
                    <input
                      required
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      placeholder="e.g. Officer Shubham Verma"
                    />
                  </div>
                </label>
                <div className="auth-row">
                  <label className="auth-field">
                    <span>Badge / service ID</span>
                    <div className="auth-input">
                      <BadgeCheck size={14} />
                      <input
                        required
                        value={badgeId}
                        onChange={(e) => setBadgeId(e.target.value)}
                        placeholder="I4C-IND-001"
                      />
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
              <span>Official email address</span>
              <div className="auth-input">
                <User size={14} />
                <input
                  required
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="officer@agency.gov.in"
                />
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
                <button
                  type="button"
                  className="auth-eye"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label="Toggle password"
                >
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </label>

            {!isSignup && (
              <div className="auth-meta">
                <label className="auth-check">
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                  Remember session
                </label>
                <button
                  type="button"
                  className="auth-link"
                  onClick={() => setNotice("Password reset email will be sent via your connected Supabase project.")}
                >
                  Forgot password?
                </button>
              </div>
            )}

            <button type="submit" className="auth-submit" disabled={loading || oauthLoading !== null}>
              {loading ? "Authenticating with Supabase…" : isSignup ? "Create Account & Inherit Profile" : "Sign In to Console"}
              {!loading && <ArrowRight size={15} />}
            </button>
          </form>

          <p className="auth-switch">
            {isSignup ? "Already have an account?" : "Need a new officer account?"}{" "}
            <button
              type="button"
              className="auth-link"
              onClick={() => {
                setMode(isSignup ? "login" : "signup");
                setError(null);
                setNotice(null);
              }}
            >
              {isSignup ? "Sign in" : "Create Account"}
            </button>
          </p>
        </div>

        <p className="auth-foot">
          <KeyRound size={11} /> Official cyber forensics network · 256-bit encrypted · Live Supabase Auth
        </p>
      </div>

      {/* ── Brand side: the attribution loop ── */}
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
            <circle
              key={r}
              cx="210"
              cy="210"
              r={r}
              fill="none"
              stroke="var(--auth-ring)"
              strokeWidth="1"
              strokeDasharray={i === 1 ? "4 10" : "none"}
              opacity={0.5 - i * 0.08}
            />
          ))}
          <polyline
            className="auth-art-path"
            points="70,250 150,150 250,180 300,96 350,210 260,300 140,290"
            fill="none"
            stroke="url(#authEdge)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {[[70, 250], [150, 150], [250, 180], [300, 96], [350, 210], [260, 300], [140, 290]].map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="6" className="auth-art-node" style={{ animationDelay: `${i * 0.26}s` }} />
          ))}
          <circle r="5" className="auth-art-packet">
            <animateMotion
              dur="7s"
              repeatCount="indefinite"
              path="M70,250 L150,150 L250,180 L300,96 L350,210 L260,300 L140,290"
            />
          </circle>
        </svg>

        <div className="auth-art-copy">
          <h2>Every rupee has a route.</h2>
          <p>Chakravyuh walks it hop by hop, names the exchange at the end, and hands you the notice to send.</p>
          <div className="auth-art-tags">
            <span><ShieldCheck size={12} /> Sec 65B ready</span>
            <span>NCRP integrated</span>
            <span>Supabase Verified</span>
          </div>
        </div>
      </aside>
    </div>
  );
}

export default AuthPage;
