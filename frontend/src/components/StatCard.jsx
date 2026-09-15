export default function StatCard({ icon, label, value }) {
  return (
    <div className="card flex items-center gap-3 p-3">
      <div className="text-accent">{icon}</div>
      <div>
        <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
        <div className="mono text-sm font-semibold">{value}</div>
      </div>
    </div>
  );
}
