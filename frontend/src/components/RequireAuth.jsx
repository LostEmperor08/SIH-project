import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { getMyProfile, getSessionUser } from "../lib/auth.js";

/**
 * Gate for the investigation surfaces. Anything behind it sends a visitor to
 * sign-in first and remembers where they were headed, so the button they
 * clicked still completes after they authenticate.
 */
export default function RequireAuth({ children, requireAdmin = false }) {
  const location = useLocation();
  const [state, setState] = useState({ checked: false, user: null, profile: null });

  useEffect(() => {
    let alive = true;
    Promise.all([getSessionUser(), getMyProfile()])
      .then(([user, profile]) => {
        if (alive) {
          setState({ checked: true, user, profile });
        }
      })
      .catch(() => {
        if (alive) {
          setState({ checked: true, user: null, profile: null });
        }
      });
    return () => {
      alive = false;
    };
  }, [location.pathname]);

  if (!state.checked) {
    return (
      <div className="workspace-shell grid min-h-[100dvh] place-items-center">
        <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Verifying officer clearance…</span>
      </div>
    );
  }

  if (!state.user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (requireAdmin && state.profile?.role !== "admin") {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}
