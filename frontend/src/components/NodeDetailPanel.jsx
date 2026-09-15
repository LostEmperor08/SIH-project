import { NODE_COLORS } from "../lib/constants.js";
import { Info } from "lucide-react";

export default function NodeDetailPanel({ node, edges }) {
  if (!node) {
    return (
      <div className="card p-4 text-sm text-slate-500">
        <div className="mb-2 flex items-center gap-2 text-slate-400"><Info size={16} /> Node Details</div>
        Click any node in the graph to inspect address, flows and evidence.
      </div>
    );
  }
  const out = edges.filter((e) => e.source === node.id);
  const inn = edges.filter((e) => e.target === node.id);

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="h-3 w-3 rounded-full" style={{ background: NODE_COLORS[node.type] }} />
        <h3 className="text-sm font-semibold">{node.label ?? node.id}</h3>
      </div>
      <div className="mono text-xs break-all rounded bg-ink-800 p-2 text-slate-300">{node.id}</div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded bg-ink-800 p-2">
          <div className="text-slate-500">Type</div>
          <div className="font-semibold">{node.type}</div>
        </div>
        <div className="rounded bg-ink-800 p-2">
          <div className="text-slate-500">Balance</div>
          <div className="font-semibold">{node.balance?.toLocaleString() ?? "—"}</div>
        </div>
      </div>

      {inn.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase text-slate-500">Inbound ({inn.length})</div>
          {inn.map((e) => <FlowRow key={e.tx_hash + "in"} e={e} dir="←" other={e.source} />)}
        </div>
      )}
      {out.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase text-slate-500">Outbound ({out.length})</div>
          {out.map((e) => <FlowRow key={e.tx_hash + "out"} e={e} dir="→" other={e.target} />)}
        </div>
      )}
    </div>
  );
}

function FlowRow({ e, dir, other }) {
  return (
    <div className="mb-1 rounded bg-ink-800/70 p-2 text-[11px] mono">
      <div className="flex justify-between text-slate-300">
        <span>{dir} {other.slice(0, 10)}…</span>
        <span className="text-accent">{e.amount.toLocaleString()} {e.token}</span>
      </div>
      <div className="mt-0.5 flex justify-between text-slate-500">
        <span className="truncate">{e.tx_hash}</span>
        <span>{new Date(e.timestamp).toLocaleTimeString()}</span>
      </div>
    </div>
  );
}
