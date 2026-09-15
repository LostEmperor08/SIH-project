import React, { useEffect, useState } from "react";
import { WorkspaceNav } from "./WorkspaceNav.jsx";
import AdminPanel from "./AdminPanel.jsx";
import { getMyProfile } from "../lib/auth.js";

export default function AdminRoute() {
  const [profile, setProfile] = useState(undefined);

  useEffect(() => {
    let alive = true;
    getMyProfile().then((p) => alive && setProfile(p));
    return () => {
      alive = false;
    };
  }, []);

  const handleNav = (route) => {
    window.location.href = route === "landing" ? "/" : "/dashboard";
  };

  return (
    <div className="workspace-shell min-h-[100dvh] text-slate-800 dark:text-slate-200">
      <WorkspaceNav activeRoute="admin" onNavigate={handleNav} />
      <main className="workspace-main mx-auto w-full max-w-[1440px] p-4 sm:p-6 lg:p-8">
        {profile === undefined ? (
          <div className="py-24 text-center text-xs font-bold text-slate-500">Verifying clearance…</div>
        ) : (
          <AdminPanel profile={profile} />
        )}
      </main>
    </div>
  );
}
