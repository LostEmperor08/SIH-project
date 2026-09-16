// =====================================================================
// Which traced transfers are evidence IN THIS CASE.
//
// Pure, dependency-free and separately tested (scripts/tests) — it decides
// what goes into a Section 65B document, so it must be provable without a
// database, a network or a browser.
// =====================================================================
/**
 * The edges that are actually EVIDENCE about the suspect address.
 *
 * This is the fix for the ledger showing "someone else's transactions".
 * The old rule was "top 50 edges by value" across the whole graph — but a
 * 2-hop graph is mostly transfers between third parties who merely appear
 * near the suspect. A transfer from an unrelated wallet to another
 * unrelated wallet is not evidence in this case, and putting it in a Sec
 * 65B ledger is worse than useless: it is a document that overstates what
 * was traced.
 *
 * The money path is what belongs:
 *   - anything flowing INTO the suspect     (how the wallet was funded)
 *   - anything flowing OUT of the suspect, and out of whatever that
 *     reached, following direction only    (where the money went)
 *
 * An edge whose source was never reached from the suspect is dropped.
 */
export function pathEdges(graph, targetAddress) {
  const nodes = graph?.nodes ?? [];
  const edges = graph?.edges ?? [];
  if (!edges.length) return [];

  const norm = (a) => String(a ?? "").toLowerCase();
  const wanted = norm(targetAddress);

  const suspects = new Set(
    nodes
      .filter((n) => n.type === "SUSPECT" || n.hop === 0 || (wanted && norm(n.id) === wanted))
      .map((n) => norm(n.id))
  );
  if (wanted) suspects.add(wanted);
  // No identifiable suspect means no defensible filter. Seal nothing rather
  // than seal the wrong thing.
  if (!suspects.size) return [];

  const out = new Map();
  for (const e of edges) {
    const k = norm(e.source);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(e);
  }

  // Forward BFS: every address the suspect's money actually reaches.
  const downstream = new Set(suspects);
  const queue = [...suspects];
  const kept = new Map();               // dedupe by source|target
  const depth = new Map(suspects.size ? [...suspects].map((a) => [a, 0]) : []);

  while (queue.length) {
    const cur = queue.shift();
    const d = depth.get(cur) ?? 0;
    for (const e of out.get(cur) ?? []) {
      const t = norm(e.target);
      const key = `${norm(e.source)}|${t}`;
      if (!kept.has(key)) kept.set(key, { ...e, hop: d + 1, direction: "OUTWARD SWEEP" });
      if (!downstream.has(t)) {
        downstream.add(t);
        depth.set(t, d + 1);
        queue.push(t);
      }
    }
  }

  // Direct inflows to the suspect: how the wallet was funded. These are hop
  // 0 — they happened before anything left.
  for (const e of edges) {
    if (!suspects.has(norm(e.target))) continue;
    const key = `${norm(e.source)}|${norm(e.target)}`;
    if (kept.has(key)) continue;
    kept.set(key, { ...e, hop: 0, direction: "INBOUND DEPOSIT" });
  }

  // Nearest the suspect first, then by value. An officer reads a ledger
  // outward from the victim's money, not in order of size.
  return [...kept.values()].sort(
    (a, b) => (a.hop - b.hop) || ((b.amount ?? 0) - (a.amount ?? 0))
  );
}
