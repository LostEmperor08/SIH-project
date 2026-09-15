import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

/**
 * Keeps one failing surface from taking the whole workspace down. Without
 * this, any throw inside a screen unmounts the tree and leaves a blank page —
 * which is what "the site cracks" looks like from the outside.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Surface failed:", error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="mx-auto my-16 w-full max-w-md px-5 text-center">
        <div className="glass-panel admin-panel rounded-2xl p-7">
          <span className="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-xl border border-[#E5B83B]/40 bg-[#E5B83B]/10 text-[#FFE28A]">
            <AlertTriangle size={18} />
          </span>
          <h2 className="text-base font-extrabold">This screen stopped responding</h2>
          <p className="mx-auto mt-2 max-w-xs text-xs leading-relaxed admin-muted">
            The rest of the workspace is unaffected. Reload to pick the case back up where you left it.
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <button type="button" className="admin-btn inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-bold" onClick={() => window.location.reload()}>
              <RefreshCw size={13} /> Reload
            </button>
            <button type="button" className="admin-btn rounded-xl px-4 py-2.5 text-xs font-bold" onClick={() => { window.location.href = "/"; }}>
              Back to overview
            </button>
          </div>
        </div>
      </div>
    );
  }
}
