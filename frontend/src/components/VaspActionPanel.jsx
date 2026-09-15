import { FileWarning, FileDown, Landmark } from "lucide-react";

export default function VaspActionPanel({ graph, onNotice, onDossier }) {
  const a = graph?.attribution;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <Landmark size={16} className="text-accent" /> VASP Action Panel
      </div>

      {!a ? (
        <p className="text-xs text-slate-500">
          {graph
            ? "Traversal did not reach a labelled VASP within hop limit. Extend depth or lower threshold."
            : "Run a trace to surface exchange attribution and legal actions."}
        </p>
      ) : (
        <>
          <div className="rounded-lg border border-blue-500/40 bg-blue-500/10 p-3">
            <div className="text-[10px] uppercase text-slate-400">Target VASP</div>
            <div className="text-lg font-bold text-blue-300">{a.exchange_name}</div>
            <div className="mt-2 space-y-1 text-[11px] mono text-slate-300">
              <Row k="Deposit Address" v={a.deposit_address} />
              <Row k="TX Hash → VASP" v={a.tx_hash} />
              <Row k="Deposit Time" v={new Date(a.deposit_timestamp).toLocaleString()} />
              <Row k="Confidence" v={`${(a.confidence * 100).toFixed(0)}% (sweep heuristic)`} />
            </div>
          </div>

          <button
            onClick={onNotice}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-500/90 px-4 py-2 text-sm font-semibold text-ink-950 hover:bg-amber-400"
          >
            <FileWarning className="h-4 w-4" /> Generate Section 94 BNSS Notice
          </button>
        </>
      )}

      <button
        onClick={onDossier}
        disabled={!graph}
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-ink-600 bg-ink-800 px-4 py-2 text-sm font-semibold text-slate-200 hover:border-accent disabled:opacity-40"
      >
        <FileDown className="h-4 w-4" /> Export Investigation Dossier (PDF)
      </button>
      <p className="text-[10px] text-slate-500">
        Dossier contains chain of custody, graph snapshot, hop timeline, VASP attribution
        evidence and cryptographic proofs (tx hashes).
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
