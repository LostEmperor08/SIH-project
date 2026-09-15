// =====================================================================
// investigate-address — THE endpoint for PS 26183
//
// Takes victim-reported wallet addresses, traces them on live chains,
// persists everything to Supabase, scores them with the AI/ML models,
// and returns a React Flow-ready graph.
//
// POST {
//   "targets": [ {"chain":"btc","address":"bc1..."},
//                {"chain":"eth","address":"0x..."} ],
//   "hops": 2,
//   "cap_per_address": 50,
//   "score": true
// }
//
// No mock data anywhere in this file. If a provider is unreachable the
// call FAILS with the provider error — it never silently substitutes
// placeholder edges, which is the behaviour your report commits to.
// =====================================================================
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";
import {
  addressHistory, Chain, CHAINS, ChainError, explorerUrl, isValidAddress,
  NormEdge, normaliseAddress, txExplorerUrl, usdPrice,
} from "../_shared/chains.ts";

const CORS = {
  "Access-Control-Allow-Origin": Deno.env.get("ALLOWED_ORIGIN") ?? "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { ...CORS, "Content-Type": "application/json" } });

const admin = () => createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  { auth: { persistSession: false } },
);

const chunk = <T>(a: T[], n: number): T[][] =>
  Array.from({ length: Math.ceil(a.length / n) }, (_, i) => a.slice(i * n, i * n + n));

// Hard ceilings. A 4-hop trace on an exchange hot wallet would otherwise
// walk half the chain and blow the function's execution budget.
const MAX_HOPS = 3;
const MAX_ADDRESSES_PER_HOP = 40;
const MAX_TOTAL_EDGES = 8_000;

interface Target { chain: Chain; address: string; }

// =====================================================================
// Multi-hop BFS over live chain data
// =====================================================================
async function traceMultiHop(
  targets: Target[], hops: number, cap: number, includeUnconfirmed = false,
): Promise<{ edges: NormEdge[]; visited: Map<string, number>; errors: string[] }> {
  const edges: NormEdge[] = [];
  const visited = new Map<string, number>();     // "chain:addr" -> hop depth
  const errors: string[] = [];
  const seenEdge = new Set<string>();

  let frontier: Target[] = targets.map((t) => ({
    chain: t.chain, address: normaliseAddress(t.chain, t.address),
  }));
  frontier.forEach((t) => visited.set(`${t.chain}:${t.address}`, 0));

  for (let depth = 0; depth <= hops; depth++) {
    if (!frontier.length || edges.length >= MAX_TOTAL_EDGES) break;

    // fetch this whole layer concurrently; the semaphore in chains.ts
    // keeps actual in-flight requests inside the free-tier limits
    const results = await Promise.allSettled(
      frontier.map((t) => addressHistory(t.chain, t.address, cap, includeUnconfirmed)),
    );

    const next = new Map<string, Target>();
    results.forEach((r, i) => {
      const t = frontier[i];
      if (r.status === "rejected") {
        errors.push(`${t.chain}:${t.address.slice(0, 12)}… ${r.reason?.message ?? r.reason}`);
        return;
      }
      for (const e of r.value) {
        const key = `${e.chain}:${e.tx_hash}:${e.vout_index}:${e.from_address}:${e.to_address}`;
        if (seenEdge.has(key)) continue;
        seenEdge.add(key);
        edges.push(e);

        // queue unvisited counterparties for the next hop
        if (depth < hops) {
          for (const nb of [e.from_address, e.to_address]) {
            const k = `${e.chain}:${nb}`;
            if (!visited.has(k) && !next.has(k)) {
              next.set(k, { chain: e.chain, address: nb });
            }
          }
        }
      }
    });

    // Expand the highest-value counterparties first. Following the money
    // is the investigative priority; an arbitrary slice would just as
    // likely follow dust.
    const valueOf = new Map<string, number>();
    for (const e of edges) {
      for (const a of [e.from_address, e.to_address]) {
        const k = `${e.chain}:${a}`;
        valueOf.set(k, (valueOf.get(k) ?? 0) + e.value_usd);
      }
    }
    frontier = [...next.entries()]
      .sort((a, b) => (valueOf.get(b[0]) ?? 0) - (valueOf.get(a[0]) ?? 0))
      .slice(0, MAX_ADDRESSES_PER_HOP)
      .map(([k, t]) => { visited.set(k, depth + 1); return t; });
  }

  return { edges, visited, errors };
}

// =====================================================================
// Persist to Supabase
// =====================================================================
async function persist(edges: NormEdge[]) {
  const sb = admin();
  const byChain = new Map<Chain, NormEdge[]>();
  for (const e of edges) {
    if (!byChain.has(e.chain)) byChain.set(e.chain, []);
    byChain.get(e.chain)!.push(e);
  }

  let wallets = 0, txs = 0;
  for (const [chain, list] of byChain) {
    const addrs = [...new Set(list.flatMap((e) => [e.from_address, e.to_address]))];
    for (const c of chunk(addrs.map((a) => ({ chain, address: a })), 500)) {
      await sb.from("wallets").upsert(c, { onConflict: "chain,address", ignoreDuplicates: true });
    }
    wallets += addrs.length;

    for (const c of chunk(list, 500)) {
      const { error, count } = await sb.from("transactions").upsert(c, {
        onConflict: "chain,tx_hash,vout_index,from_address,to_address",
        ignoreDuplicates: true, count: "exact",
      });
      if (error) console.error("tx upsert", chain, error.message);
      txs += count ?? 0;
    }
    await sb.rpc("refresh_wallet_stats", { p_chain: chain });
  }

  await sb.rpc("apply_threat_intel");
  return { wallets, transactions: txs, chains: [...byChain.keys()] };
}

// =====================================================================
// Scoring — calls the FastAPI ML service when configured.
//
// If ML_API_URL is unset the function still returns a graph, scored by
// the deterministic SQL rules. Degrading to rules-only beats returning a
// 500: an officer with rule-based scores is far better served than an
// officer with an error page.
// =====================================================================
async function scoreWithML(
  edges: NormEdge[], addresses: string[], chain: Chain, flags: Record<string, string[]>,
): Promise<Record<string, any> | null> {
  const url = Deno.env.get("ML_API_URL");
  if (!url) return null;

  try {
    const res = await fetch(`${url.replace(/\/$/, "")}/ml/score`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${Deno.env.get("ML_API_KEY") ?? ""}`,
      },
      body: JSON.stringify({
        chain,
        addresses: addresses.slice(0, 200),
        edges: edges.map((e) => ({
          from_address: e.from_address, to_address: e.to_address,
          value_usd: e.value_usd, ts: new Date(e.block_time).getTime() / 1000,
          tx_hash: e.tx_hash,
        })),
        sanctioned: flags.sanctioned ?? [],
        mixers: flags.mixers ?? [],
        exchanges: flags.exchanges ?? [],
        darknet: flags.darknet ?? [],
        bridges: flags.bridges ?? [],
        explain: true,
      }),
      signal: AbortSignal.timeout(25_000),
    });
    if (!res.ok) {
      console.error("ML service", res.status, (await res.text()).slice(0, 300));
      return null;
    }
    const j = await res.json();
    return Object.fromEntries((j.results ?? []).map((r: any) => [r.address, r]));
  } catch (e) {
    console.error("ML service unreachable:", e.message);
    return null;
  }
}

async function persistPredictions(chain: Chain, scores: Record<string, any>) {
  const sb = admin();
  const rows = Object.values(scores).map((r: any) => ({
    chain, address: r.address,
    risk_score: r.risk_score, risk_band: r.risk_band,
    illicit_probability: r.illicit_probability, anomaly_score: r.anomaly_score,
    rule_score: r.rule_score,
    vasp_type: r.vasp_attribution?.type ?? null,
    vasp_confidence: r.vasp_attribution?.confidence ?? null,
    typologies: r.typologies ?? [], explanation: r.explanation ?? [],
    narrative: r.narrative ?? null,
    recommended_actions: r.recommended_actions ?? [],
    hops_to_exchange: r.hops_to_exchange, hops_to_sanctioned: r.hops_to_sanctioned,
    hops_to_mixer: r.hops_to_mixer,
  }));
  for (const c of chunk(rows, 400)) {
    const { error } = await sb.from("ml_predictions").insert(c);
    if (error) console.error("ml_predictions insert", error.message);
  }
  return rows.length;
}

// =====================================================================
// Build the React Flow graph
// =====================================================================
function buildGraph(
  edges: NormEdge[], visited: Map<string, number>, targets: Target[],
  wallets: Map<string, any>, scores: Record<string, any> | null,
) {
  const targetKeys = new Set(targets.map((t) => `${t.chain}:${normaliseAddress(t.chain, t.address)}`));

  // aggregate parallel edges between the same pair — a hundred separate
  // lines between two nodes is unreadable; one weighted line is evidence
  const agg = new Map<string, {
    chain: Chain; from: string; to: string;
    value_usd: number; count: number; first: string; last: string; hashes: string[];
  }>();
  for (const e of edges) {
    const k = `${e.chain}:${e.from_address}->${e.to_address}`;
    const cur = agg.get(k);
    if (cur) {
      cur.value_usd += e.value_usd; cur.count++;
      if (e.block_time < cur.first) cur.first = e.block_time;
      if (e.block_time > cur.last) cur.last = e.block_time;
      if (cur.hashes.length < 5) cur.hashes.push(e.tx_hash);
    } else {
      agg.set(k, {
        chain: e.chain, from: e.from_address, to: e.to_address,
        value_usd: e.value_usd, count: 1,
        first: e.block_time, last: e.block_time, hashes: [e.tx_hash],
      });
    }
  }

  const nodeKeys = new Set<string>();
  for (const a of agg.values()) {
    nodeKeys.add(`${a.chain}:${a.from}`);
    nodeKeys.add(`${a.chain}:${a.to}`);
  }

  const nodes = [...nodeKeys].map((k) => {
    const [chain, ...rest] = k.split(":");
    const address = rest.join(":");
    const w = wallets.get(k) ?? {};
    const s = scores?.[address];
    const isTarget = targetKeys.has(k);

    let inUsd = 0, outUsd = 0, deg = 0;
    for (const a of agg.values()) {
      if (a.chain !== chain) continue;
      if (a.to === address) { inUsd += a.value_usd; deg++; }
      if (a.from === address) { outUsd += a.value_usd; deg++; }
    }

    const entity = w.entity_type && w.entity_type !== "unknown"
      ? w.entity_type
      : (s?.vasp_attribution?.type && !s.vasp_attribution.abstained
          ? s.vasp_attribution.type : "unknown");

    return {
      id: k,
      type: isTarget ? "target" : entity === "unknown" ? "wallet" : entity,
      data: {
        address, chain,
        label: w.vasp_name ?? `${address.slice(0, 8)}…${address.slice(-4)}`,
        hop: visited.get(k) ?? null,
        isTarget,
        entity,
        vaspName: w.vasp_name ?? null,
        sanctioned: !!w.is_sanctioned,
        riskScore: s?.risk_score ?? null,
        riskBand: s?.risk_band ?? null,
        narrative: s?.narrative ?? null,
        typologies: s?.typologies ?? [],
        recommendedActions: s?.recommended_actions ?? [],
        explanation: s?.explanation ?? [],
        hopsToExchange: s?.hops_to_exchange ?? null,
        hopsToSanctioned: s?.hops_to_sanctioned ?? null,
        inUsd: +inUsd.toFixed(2),
        outUsd: +outUsd.toFixed(2),
        degree: deg,
        explorerUrl: explorerUrl(chain as Chain, address),
      },
    };
  });

  const flowEdges = [...agg.values()].map((a, i) => ({
    id: `e${i}`,
    source: `${a.chain}:${a.from}`,
    target: `${a.chain}:${a.to}`,
    label: a.value_usd >= 1
      ? `$${a.value_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
      : `${a.count} tx`,
    animated: a.value_usd > 10_000,
    data: {
      chain: a.chain, valueUsd: +a.value_usd.toFixed(2), txCount: a.count,
      firstSeen: a.first, lastSeen: a.last,
      txHashes: a.hashes,
      explorerUrls: a.hashes.map((h) => txExplorerUrl(a.chain, h)),
    },
  }));

  return { nodes, edges: flowEdges };
}

// =====================================================================
Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const t0 = Date.now();
  try {
    const body = await req.json().catch(() => ({}));
    const rawTargets = body.targets ?? [];
    const hops = Math.min(Number(body.hops ?? 2), MAX_HOPS);
    const cap = Math.min(Number(body.cap_per_address ?? 50), 100);
    const wantScore = body.score !== false;
    // Mempool transactions are excluded by default: an unconfirmed transfer
    // can be replaced or dropped, so treating it as a settled fund movement
    // would put unreliable evidence in a dossier.
    const includeUnconfirmed = body.include_unconfirmed === true;

    if (!Array.isArray(rawTargets) || rawTargets.length === 0) {
      return json({ error: "targets[] required, e.g. [{chain:'btc',address:'bc1...'}]" }, 400);
    }
    if (rawTargets.length > 10) {
      return json({ error: "at most 10 targets per request" }, 400);
    }

    // validate everything up front — one bad address should not send
    // nine good ones through a pointless multi-hop trace
    const targets: Target[] = [];
    for (const t of rawTargets) {
      if (!CHAINS.includes(t.chain)) {
        return json({ error: `unsupported chain '${t.chain}'. Supported: ${CHAINS.join(", ")}` }, 400);
      }
      if (!isValidAddress(t.chain, String(t.address ?? ""))) {
        return json({ error: `'${t.address}' is not a valid ${t.chain} address` }, 400);
      }
      targets.push({ chain: t.chain, address: normaliseAddress(t.chain, t.address) });
    }

    // ---- 1. live trace -------------------------------------------
    const { edges, visited, errors } = await traceMultiHop(
      targets, hops, cap, includeUnconfirmed);

    if (edges.length === 0) {
      return json({
        ok: false,
        error: "no transactions found for the supplied addresses",
        detail: "These addresses may be unused, or the provider may be unreachable. " +
                "No placeholder data is returned.",
        providerErrors: errors,
        targets,
      }, 404);
    }

    // ---- 2. persist ----------------------------------------------
    const stats = await persist(edges);

    // ---- 3. entity flags for the ML call --------------------------
    const sb = admin();
    const chains = [...new Set(edges.map((e) => e.chain))];
    const allAddrs = [...new Set(edges.flatMap((e) => [e.from_address, e.to_address]))];

    const { data: walletRows } = await sb.from("wallets")
      .select("chain,address,entity_type,vasp_name,is_sanctioned")
      .in("chain", chains).in("address", allAddrs.slice(0, 1000));

    const wallets = new Map((walletRows ?? []).map((w: any) => [`${w.chain}:${w.address}`, w]));
    const flags: Record<string, string[]> = {
      sanctioned: [], mixers: [], exchanges: [], darknet: [], bridges: [],
    };
    for (const w of walletRows ?? []) {
      if (w.is_sanctioned) flags.sanctioned.push(w.address);
      if (w.entity_type === "mixer") flags.mixers.push(w.address);
      if (w.entity_type === "exchange") flags.exchanges.push(w.address);
      if (w.entity_type === "darknet") flags.darknet.push(w.address);
      if (w.entity_type === "bridge") flags.bridges.push(w.address);
    }

    // ---- 4. score -------------------------------------------------
    let scores: Record<string, any> | null = null;
    let scoredCount = 0;
    if (wantScore) {
      const primaryChain = targets[0].chain;
      scores = await scoreWithML(
        edges.filter((e) => e.chain === primaryChain),
        allAddrs, primaryChain, flags,
      );
      if (scores) scoredCount = await persistPredictions(primaryChain, scores);
      else {
        // fall back to the deterministic SQL engine
        for (const c of chains) await sb.rpc("run_detection_pipeline", { p_chain: c });
      }
    }

    // ---- 5. graph -------------------------------------------------
    const graph = buildGraph(edges, visited, targets, wallets, scores);

    const prices: Record<string, number> = {};
    for (const c of chains) prices[c] = await usdPrice(c);

    return json({
      ok: true,
      dataSource: "live",
      targets,
      hops,
      providers: {
        btc: "blockstream.info/api", eth: "eth.blockscout.com/api/v2",
        polygon: "polygon.blockscout.com/api/v2", tron: "apilist.tronscanapi.com",
        bsc: Deno.env.get("ETHERSCAN_API_KEY") ? "api.etherscan.io/v2 (chainid=56)" : "not configured",
      },
      stats: {
        ...stats,
        edgesTraced: edges.length,
        addressesDiscovered: visited.size,
        nodes: graph.nodes.length,
        graphEdges: graph.edges.length,
        totalValueUsd: +edges.reduce((s, e) => s + e.value_usd, 0).toFixed(2),
        scored: scoredCount,
        scoringMode: scores ? "ml" : "rules_only",
      },
      prices: { note: "current spot rate applied to all transfers; not historical cost basis",
                usd: prices },
      providerErrors: errors,
      graph,
      elapsedMs: Date.now() - t0,
    });

  } catch (e) {
    console.error(e);
    const status = e instanceof ChainError ? 502 : 500;
    return json({ ok: false, error: String(e?.message ?? e), dataSource: "live" }, status);
  }
});
