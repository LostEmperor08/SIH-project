import React from "react";

/**
 * Ambient radar sweep behind the whole app. Only `transform` animates, so the
 * browser keeps it on the compositor and never re-layouts while it spins.
 */
export default function AmbientRadar() {
  return (
    <div className="ambient-radar" aria-hidden="true">
      <div className="ambient-radar__rings" />
      <div className="ambient-radar__sweep" />
      <div className="ambient-radar__grid" />
    </div>
  );
}
