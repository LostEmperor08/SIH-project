export default function TimelinePanel({ edges }) {
  if (!edges.length) return null;
  const sorted = [...edges].sort((x, y) => +new Date(x.timestamp) - +new Date(y.timestamp));
  const t0 = +new Date(sorted[0].timestamp);

  return (
    <div className="card p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-400">Chronological Hops</h3>
      <ol className="relative space-y-3 border-l border-ink-600 pl-4">
        {sorted.map((e, i) => {
          const gapMin = ((+new Date(e.timestamp) - t0) / 60000).toFixed(1);
          return (
            <li key={e.tx_hash} className="relative text-xs">
              <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-accent" />
              <div className="mono text-slate-300">
                <span className="text-slate-500">#{i + 1}</span> {e.source.slice(0, 8)}… → {e.target.slice(0, 8)}…
              </div>
              <div className="flex justify-between text-slate-500">
                <span>{e.amount.toLocaleString()} {e.token}</span>
                <span>t+{gapMin} min</span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
