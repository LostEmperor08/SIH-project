import { FileWarning, FileDown, Landmark } from "lucide-react";

export default function VaspActionPanel({ graph, onNotice, onDossier }) {
  const a = graph?.attribution;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Landmark size={16} className="text-accent" /> Crypto Exchange Actions
      </div>

      {!a ? (
        <p className="text-xs text-slate-500">
          {graph
            ? "Money trail did not reach a known exchange within step limit. Try increasing tracing depth."
            : "Run a trace to find receiving exchanges and official actions."}
        </p>
      ) : (
        <>
          <div className="rounded-lg border border-blue-500/40 bg-blue-500/10 p-3">
            <div className="text-[10px] uppercase text-slate-400">Identified Exchange</div>
            <div className="text-lg font-bold text-blue-300">{a.exchange_name}</div>
            <div className="mt-2 space-y-1 text-[11px] mono text-slate-300">
              <Row k="Deposit Address" v={a.deposit_address} />
              <Row k="Transfer Hash → Exchange" v={a.tx_hash} />
              <Row k="Deposit Time" v={new Date(a.deposit_timestamp).toLocaleString()} />
              <Row k="Match Confidence" v={`${(a.confidence * 100).toFixed(0)}% (Automated Match)`} />
            </div>
          </div>

          <button
            onClick={onNotice}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-500/90 px-4 py-2 text-sm font-semibold text-ink-950 hover:bg-amber-400"
          >
            <FileWarning className="h-4 w-4" /> Issue Section 91 Preservation Notice
          </button>
        </>
      )}

      <button
        onClick={onDossier}
        disabled={!graph}
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-ink-600 bg-ink-800 px-4 py-2 text-sm font-semibold text-slate-200 hover:border-accent disabled:opacity-40"
      >
        <FileDown className="h-4 w-4" /> Download Official Investigation Report
      </button>
      <p className="text-[10px] text-slate-500">
        Report contains step-by-step money trail, exchange details, transfer timeline, and court-ready evidence hashes.
      </p>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-slate-500 shrink-0">{k}</span>
      <span className="truncate text-right">{v}</span>
    </div>
  );
}
