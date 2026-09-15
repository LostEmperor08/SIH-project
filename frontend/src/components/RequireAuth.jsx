import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { getSessionUser } from "../lib/auth.js";

/**
 * Gate for the investigation surfaces. Anything behind it sends a visitor to
 * sign-in first and remembers where they were headed, so the button they
 * clicked still completes after they authenticate.
 */
export default function RequireAuth({ children, requireAdmin = false }) {
  const location = useLocation();
  const [state, setState] = useState({ checked: false, user: null });

  useEffect(() => {
    let alive = true;
    getSessionUser()
      .then((user) => alive && setState({ checked: true, user }))
      .catch(() => alive && setState({ checked: true, user: null }));
    return () => {
      alive = false;
    };
  }, [location.pathname]);

  if (!state.checked) {
    return (
      <div className="grid min-h-[60vh] place-items-center">
        <span className="text-[11px] font-bold uppercase tracking-wider admin-muted">Verifying clearance…</span>
      </div>
    );
  }

  if (!state.user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (requireAdmin && state.user.role !== "admin") {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}
