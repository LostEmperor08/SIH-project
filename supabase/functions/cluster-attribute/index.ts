// =====================================================================
// cluster-attribute — wallet clustering + VASP attribution
//
// 1. Common-Input-Ownership heuristic (Bitcoin): every address that
//    co-signs the inputs of one transaction is controlled by one entity.
//    Implemented as weighted union-find over the ingested edge set.
// 2. Behavioural fingerprinting labels each cluster as
//    exchange / mixer / gambling / bridge / merchant / p2p.
//
// POST { "chain": "btc" }
// =====================================================================
import { admin, chunk, CORS, json } from "../_shared/lib.ts";

// ---------------------------------------------------------------------
// Union-Find (disjoint set) with path compression + union by size
// ---------------------------------------------------------------------
class UnionFind {
  private parent = new Map<string, string>();
  private size = new Map<string, number>();

  find(x: string): string {
    if (!this.parent.has(x)) { this.parent.set(x, x); this.size.set(x, 1); return x; }
    let root = x;
    while (this.parent.get(root) !== root) root = this.parent.get(root)!;
    // path compression
    let cur = x;
    while (this.parent.get(cur) !== root) {
      const next = this.parent.get(cur)!;
      this.parent.set(cur, root);
      cur = next;
    }
    return root;
  }

  union(a: string, b: string) {
    let ra = this.find(a), rb = this.find(b);
    if (ra === rb) return;
    if (this.size.get(ra)! < this.size.get(rb)!) [ra, rb] = [rb, ra];
    this.parent.set(rb, ra);
    this.size.set(ra, this.size.get(ra)! + this.size.get(rb)!);
  }

  groups(): Map<string, string[]> {
    const g = new Map<string, string[]>();
    for (const k of this.parent.keys()) {
      const r = this.find(k);
      (g.get(r) ?? g.set(r, []).get(r)!).push(k);
    }
    return g;
  }
}

// ---------------------------------------------------------------------
// VASP / entity fingerprints.  Each rule returns 0..1 confidence.
// These are behavioural, not name-based — that is the point: we infer
// what an unlabelled cluster *is* from how it moves money.
// ---------------------------------------------------------------------
type Profile = {
  size: number; txCount: number; fanIn: number; fanOut: number;
  volumeUsd: number; avgValue: number; roundRatio: number;
  uniformityScore: number;      // how equal-sized the outputs are (mixers)
  reuseRatio: number;           // address reuse (exchanges reuse hot wallets)
  burstiness: number;           // std/mean of inter-tx gaps
  peelRatio: number;
};

function attribute(p: Profile): { entity: string; confidence: number; evidence: string[] } {
  const ev: string[] = [];
  const score: Record<string, number> = {
    exchange: 0, mixer: 0, gambling: 0, bridge: 0, merchant: 0, p2p: 0,
  };

  // Exchange: huge cluster, very high fan-in AND fan-out, heavy reuse
  if (p.size > 200) { score.exchange += 0.3; ev.push(`cluster size ${p.size} (>200)`); }
  if (p.fanIn > 500 && p.fanOut > 500) { score.exchange += 0.35; ev.push("bidirectional fan >500"); }
  if (p.reuseRatio > 0.6) { score.exchange += 0.2; ev.push(`hot-wallet reuse ${p.reuseRatio.toFixed(2)}`); }
  if (p.volumeUsd > 1e7) { score.exchange += 0.15; ev.push("volume >$10M"); }

  // Mixer: near-uniform output denominations, high fan-out, low reuse
  if (p.uniformityScore > 0.75) { score.mixer += 0.4; ev.push(`uniform denominations ${p.uniformityScore.toFixed(2)}`); }
  if (p.fanOut > 100 && p.reuseRatio < 0.15) { score.mixer += 0.3; ev.push("high fan-out, no address reuse"); }
  if (p.roundRatio > 0.5) { score.mixer += 0.2; ev.push("round-denomination outputs"); }
  if (p.peelRatio > 0.4) { score.mixer += 0.15; ev.push("peel-chain behaviour"); }

  // Gambling: very many tiny bidirectional transfers, bursty
  if (p.avgValue < 120 && p.txCount > 400) { score.gambling += 0.45; ev.push("micro-value, high frequency"); }
  if (p.burstiness > 2.2) { score.gambling += 0.2; ev.push("bursty activity"); }

  // Bridge: one-way concentration — many in, one or two out
  if (p.fanIn > 200 && p.fanOut < 6) { score.bridge += 0.55; ev.push("many-to-few concentration"); }

  // Merchant: steady many-in / few-out, modest values
  if (p.fanIn > 30 && p.fanOut < 15 && p.burstiness < 1.0) { score.merchant += 0.4; ev.push("steady inbound, low churn"); }

  // P2P / individual: small cluster, low counts
  if (p.size <= 5 && p.txCount < 60) { score.p2p += 0.5; ev.push("small personal-scale cluster"); }

  const [entity, confidence] = Object.entries(score).sort((a, b) => b[1] - a[1])[0];
  return confidence >= 0.4
    ? { entity, confidence: Math.min(1, confidence), evidence: ev }
    : { entity: "unknown", confidence: 0, evidence: ev };
}

// ---------------------------------------------------------------------
Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  try {
    const { chain = "btc", limit = 20000 } =
      req.method === "POST" ? await req.json().catch(() => ({})) : {};
    const sb = admin();
    const t0 = Date.now();

    // ---- 1. Build the co-spend sets from raw tx inputs -------------
    const { data: txs, error } = await sb
      .from("transactions")
      .select("tx_hash, from_address, to_address, value_usd, block_time, raw")
      .eq("chain", chain)
      .order("block_time", { ascending: false })
      .limit(limit);
    if (error) throw error;

    const uf = new UnionFind();
    const stats = new Map<string, { in: Set<string>; out: Set<string>; vals: number[]; times: number[] }>();
    const touch = (a: string) => stats.get(a) ??
      (stats.set(a, { in: new Set(), out: new Set(), vals: [], times: [] }), stats.get(a)!);

    for (const t of txs ?? []) {
      // common-input-ownership
      const inputs: string[] = (t.raw as any)?.inputs ?? [];
      for (let i = 1; i < inputs.length; i++) uf.union(inputs[0], inputs[i]);
      if (inputs.length === 0) uf.find(t.from_address);   // ensure vertex exists

      const s = touch(t.from_address), d = touch(t.to_address);
      s.out.add(t.to_address); s.vals.push(Number(t.value_usd));
      s.times.push(new Date(t.block_time).getTime());
      d.in.add(t.from_address); d.vals.push(Number(t.value_usd));
    }

    // ---- 2. Materialise clusters -----------------------------------
    const groups = uf.groups();
    const clusterRows: any[] = [];
    const memberPairs: { root: string; address: string }[] = [];

    for (const [root, members] of groups) {
      // aggregate the cluster profile
      const agg = { in: new Set<string>(), out: new Set<string>(), vals: [] as number[], times: [] as number[] };
      let reuseHits = 0;
      for (const m of members) {
        const s = stats.get(m); if (!s) continue;
        s.in.forEach((x) => agg.in.add(x));
        s.out.forEach((x) => agg.out.add(x));
        agg.vals.push(...s.vals); agg.times.push(...s.times);
        if (s.vals.length > 1) reuseHits++;
      }
      const vals = agg.vals.filter((v) => v > 0);
      const mean = vals.reduce((a, b) => a + b, 0) / (vals.length || 1);
      const sd = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / (vals.length || 1));
      const gaps = agg.times.sort((a, b) => a - b).slice(1).map((t, i) => t - agg.times[i]);
      const gMean = gaps.reduce((a, b) => a + b, 0) / (gaps.length || 1);
      const gSd = Math.sqrt(gaps.reduce((a, b) => a + (b - gMean) ** 2, 0) / (gaps.length || 1));

      const profile: Profile = {
        size: members.length,
        txCount: vals.length,
        fanIn: agg.in.size,
        fanOut: agg.out.size,
        volumeUsd: vals.reduce((a, b) => a + b, 0),
        avgValue: mean,
        roundRatio: vals.filter((v) => v % 100 === 0).length / (vals.length || 1),
        uniformityScore: mean > 0 ? Math.max(0, 1 - sd / mean) : 0,
        reuseRatio: reuseHits / (members.length || 1),
        burstiness: gMean > 0 ? gSd / gMean : 0,
        peelRatio: vals.filter((v, i) => i > 0 && v > vals[i - 1] * 0.7 && v < vals[i - 1] * 0.98).length /
                   (vals.length || 1),
      };

      const { entity, confidence, evidence } = attribute(profile);

      clusterRows.push({
        chain, root_address: root, size: members.length,
        entity_type: entity, vasp_confidence: confidence || null,
        vasp_name: confidence >= 0.6 ? `${entity.toUpperCase()}-${root.slice(0, 6)}` : null,
        attribution_evidence: evidence.map((e) => ({ signal: e })),
        total_volume_usd: Math.round(profile.volumeUsd * 100) / 100,
        heuristic: "common_input_ownership+behavioural",
      });
      for (const m of members) memberPairs.push({ root, address: m });
    }

    for (const c of chunk(clusterRows, 300)) {
      const { error: e } = await sb.from("clusters")
        .upsert(c, { onConflict: "chain,root_address" });
      if (e) console.error(e.message);
    }

    // link members via a SQL helper (resolves address -> wallet_id)
    await sb.rpc("link_cluster_members", { p_chain: chain, p_pairs: memberPairs });

    // propagate cluster entity labels down to member wallets
    await sb.rpc("propagate_cluster_labels", { p_chain: chain });

    return json({
      ok: true, chain,
      transactionsScanned: txs?.length ?? 0,
      clusters: clusterRows.length,
      addressesClustered: memberPairs.length,
      largestCluster: Math.max(0, ...clusterRows.map((c) => c.size)),
      attributed: clusterRows.filter((c) => c.vasp_name).length,
      elapsedMs: Date.now() - t0,
    });
  } catch (e) {
    console.error(e);
    return json({ ok: false, error: String(e.message ?? e) }, 500);
  }
});
