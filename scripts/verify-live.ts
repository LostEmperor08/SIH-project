// =====================================================================
// verify-live.ts — prove the pipeline on YOUR addresses, right now.
//
// Standalone: no Supabase, no deployment, no ML service. It hits the live
// providers, builds the graph, and prints what it found. If this prints
// real transactions for your addresses, the edge function will too.
//
//   deno run --allow-net --allow-env scripts/verify-live.ts \
//     btc:bc1qxxxxxxxx eth:0xyyyyyyyy tron:TZZZZZZZZ
//
// Write the graph to a file for React Flow:
//   deno run --allow-net --allow-env --allow-write scripts/verify-live.ts \
//     btc:bc1q... eth:0x... --hops 2 --out graph.json
// =====================================================================
import {
  addressHistory, Chain, CHAINS, explorerUrl, isValidAddress,
  NormEdge, normaliseAddress, usdPrice,
} from "../supabase/functions/_shared/chains.ts";

const args = [...Deno.args];
const flag = (name: string, def: string) => {
  const i = args.indexOf(`--${name}`);
  if (i === -1) return def;
  const v = args[i + 1];
  args.splice(i, 2);
  return v ?? def;
};

const hops = Number(flag("hops", "1"));
const cap = Number(flag("cap", "50"));
const outFile = flag("out", "");
const includeUnconfirmed = args.includes("--include-unconfirmed");
if (includeUnconfirmed) args.splice(args.indexOf("--include-unconfirmed"), 1);

const targets = args.map((a) => {
  const i = a.indexOf(":");
  if (i === -1) {
    console.error(`bad argument '${a}' — use chain:address, e.g. btc:bc1q...`);
    Deno.exit(1);
  }
  const chain = a.slice(0, i) as Chain;
  const address = a.slice(i + 1);
  if (!CHAINS.includes(chain)) {
    console.error(`unsupported chain '${chain}'. Supported: ${CHAINS.join(", ")}`);
    Deno.exit(1);
  }
  if (!isValidAddress(chain, address)) {
    console.error(`'${address}' is not a valid ${chain} address`);
    Deno.exit(1);
  }
  return { chain, address: normaliseAddress(chain, address) };
});

if (!targets.length) {
  console.error(
    "usage: deno run --allow-net --allow-env scripts/verify-live.ts " +
    "btc:<addr> eth:<addr> [--hops 2] [--cap 50] [--out graph.json]");
  Deno.exit(1);
}

const fmt = (n: number) =>
  n >= 1 ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : `$${n.toFixed(2)}`;
const short = (a: string) => a.length > 22 ? `${a.slice(0, 10)}…${a.slice(-6)}` : a;

console.log("=".repeat(72));
console.log("CHAKRAVYUH SETU — live data verification");
console.log(`${new Date().toISOString()}   hops=${hops}  cap=${cap}/address`);
console.log("=".repeat(72));

// ---- spot prices -----------------------------------------------------
console.log("\nSpot prices");
const chains = [...new Set(targets.map((t) => t.chain))];
const prices: Record<string, number> = {};
for (const c of chains) {
  prices[c] = await usdPrice(c);
  console.log(`  ${c.padEnd(8)} $${prices[c].toLocaleString()}`);
  if (prices[c] === 0) {
    console.log(`           (price lookup failed — USD values on ${c} will read 0)`);
  }
}

// ---- multi-hop trace -------------------------------------------------
const all: NormEdge[] = [];
const visited = new Map<string, number>();
const seenEdge = new Set<string>();
const errors: string[] = [];

let frontier = [...targets];
frontier.forEach((t) => visited.set(`${t.chain}:${t.address}`, 0));

for (let depth = 0; depth <= hops; depth++) {
  if (!frontier.length) break;
  console.log(`\nHop ${depth} — fetching ${frontier.length} address(es)`);

  const res = await Promise.allSettled(
    frontier.map((t) => addressHistory(t.chain, t.address, cap, includeUnconfirmed)));

  const next = new Map<string, { chain: Chain; address: string }>();
  res.forEach((r, i) => {
    const t = frontier[i];
    if (r.status === "rejected") {
      const msg = r.reason?.message ?? String(r.reason);
      errors.push(`${t.chain}:${t.address} — ${msg}`);
      console.log(`  ✗ ${t.chain}:${short(t.address)}  ${msg}`);
      return;
    }
    let added = 0, value = 0;
    for (const e of r.value) {
      const k = `${e.chain}:${e.tx_hash}:${e.vout_index}:${e.from_address}:${e.to_address}`;
      if (seenEdge.has(k)) continue;
      seenEdge.add(k);
      all.push(e); added++; value += e.value_usd;
      if (depth < hops) {
        for (const nb of [e.from_address, e.to_address]) {
          const nk = `${e.chain}:${nb}`;
          if (!visited.has(nk) && !next.has(nk)) next.set(nk, { chain: e.chain, address: nb });
        }
      }
    }
    console.log(`  ✓ ${t.chain}:${short(t.address)}  ${added} transfers, ${fmt(value)}`);
  });

  // follow the money: expand highest-value counterparties first
  const valueOf = new Map<string, number>();
  for (const e of all) {
    for (const a of [e.from_address, e.to_address]) {
      const k = `${e.chain}:${a}`;
      valueOf.set(k, (valueOf.get(k) ?? 0) + e.value_usd);
    }
  }
  frontier = [...next.entries()]
    .sort((a, b) => (valueOf.get(b[0]) ?? 0) - (valueOf.get(a[0]) ?? 0))
    .slice(0, 40)
    .map(([k, t]) => { visited.set(k, depth + 1); return t; });
}

if (!all.length) {
  console.log("\n" + "=".repeat(72));
  console.log("NO TRANSACTIONS FOUND.");
  console.log("These addresses may be unused, or a provider may be unreachable.");
  if (errors.length) {
    console.log("\nProvider errors:");
    errors.forEach((e) => console.log(`  ${e}`));
  }
  console.log("\nNo placeholder data is substituted — this is the fail-closed behaviour.");
  Deno.exit(2);
}

// ---- summary ---------------------------------------------------------
const addrs = new Set(all.flatMap((e) => [`${e.chain}:${e.from_address}`, `${e.chain}:${e.to_address}`]));
const totalUsd = all.reduce((s, e) => s + e.value_usd, 0);
const times = all.map((e) => Date.parse(e.block_time)).filter((t) => !Number.isNaN(t));

console.log("\n" + "=".repeat(72));
console.log("RESULT");
console.log("=".repeat(72));
console.log(`  transfers traced   ${all.length}`);
console.log(`  addresses in graph ${addrs.size}`);
console.log(`  total value        ${fmt(totalUsd)}`);
if (times.length) {
  console.log(`  time span          ${new Date(Math.min(...times)).toISOString().slice(0, 10)}` +
              ` → ${new Date(Math.max(...times)).toISOString().slice(0, 10)}`);
}

// ---- per-target money flow ------------------------------------------
for (const t of targets) {
  const inb = all.filter((e) => e.chain === t.chain && e.to_address === t.address);
  const out = all.filter((e) => e.chain === t.chain && e.from_address === t.address);
  const inUsd = inb.reduce((s, e) => s + e.value_usd, 0);
  const outUsd = out.reduce((s, e) => s + e.value_usd, 0);

  console.log("\n" + "-".repeat(72));
  console.log(`${t.chain.toUpperCase()}  ${t.address}`);
  console.log(`  ${explorerUrl(t.chain, t.address)}`);
  console.log(`  received  ${String(inb.length).padStart(4)} transfers  ${fmt(inUsd)}` +
              `  from ${new Set(inb.map((e) => e.from_address)).size} distinct senders`);
  console.log(`  sent      ${String(out.length).padStart(4)} transfers  ${fmt(outUsd)}` +
              `  to   ${new Set(out.map((e) => e.to_address)).size} distinct recipients`);
  console.log(`  net       ${fmt(inUsd - outUsd)}`);

  const top = [...inb, ...out].sort((a, b) => b.value_usd - a.value_usd).slice(0, 5);
  if (top.length) {
    console.log("  largest transfers:");
    for (const e of top) {
      const dir = e.to_address === t.address ? "IN  <-" : "OUT ->";
      const cp = e.to_address === t.address ? e.from_address : e.to_address;
      console.log(`    ${dir} ${short(cp).padEnd(20)} ${fmt(e.value_usd).padStart(12)}` +
                  `  ${e.block_time.slice(0, 10)}  ${e.tx_hash.slice(0, 16)}…`);
    }
  }
}

// ---- top counterparties across the whole graph ----------------------
const cp = new Map<string, { inUsd: number; outUsd: number; n: number }>();
for (const e of all) {
  const a = cp.get(e.to_address) ?? { inUsd: 0, outUsd: 0, n: 0 };
  a.inUsd += e.value_usd; a.n++; cp.set(e.to_address, a);
  const b = cp.get(e.from_address) ?? { inUsd: 0, outUsd: 0, n: 0 };
  b.outUsd += e.value_usd; b.n++; cp.set(e.from_address, b);
}
const targetAddrs = new Set(targets.map((t) => t.address));
const ranked = [...cp.entries()]
  .filter(([a]) => !targetAddrs.has(a))
  .sort((x, y) => (y[1].inUsd + y[1].outUsd) - (x[1].inUsd + x[1].outUsd))
  .slice(0, 10);

console.log("\n" + "-".repeat(72));
console.log("TOP COUNTERPARTIES (candidate VASP endpoints)");
console.log("-".repeat(72));
console.log("  " + "address".padEnd(22) + "txs".padStart(5) +
            "received".padStart(14) + "sent".padStart(14) + "  hop");
for (const [a, s] of ranked) {
  const chain = all.find((e) => e.from_address === a || e.to_address === a)!.chain;
  const hop = visited.get(`${chain}:${a}`);
  console.log("  " + short(a).padEnd(22) + String(s.n).padStart(5) +
              fmt(s.inUsd).padStart(14) + fmt(s.outUsd).padStart(14) +
              String(hop ?? "-").padStart(5));
}
console.log("\n  A high-fan-in address with heavy two-way volume is the likely");
console.log("  exchange/VASP endpoint — that is what the VASP model scores.");

if (errors.length) {
  console.log("\n" + "-".repeat(72));
  console.log(`PROVIDER ERRORS (${errors.length})`);
  errors.forEach((e) => console.log(`  ${e}`));
}

// ---- React Flow graph ------------------------------------------------
if (outFile) {
  const agg = new Map<string, { chain: Chain; from: string; to: string;
                                value_usd: number; count: number; hashes: string[] }>();
  for (const e of all) {
    const k = `${e.chain}:${e.from_address}->${e.to_address}`;
    const c = agg.get(k);
    if (c) { c.value_usd += e.value_usd; c.count++; if (c.hashes.length < 5) c.hashes.push(e.tx_hash); }
    else agg.set(k, { chain: e.chain, from: e.from_address, to: e.to_address,
                      value_usd: e.value_usd, count: 1, hashes: [e.tx_hash] });
  }
  const nodeKeys = new Set<string>();
  for (const a of agg.values()) { nodeKeys.add(`${a.chain}:${a.from}`); nodeKeys.add(`${a.chain}:${a.to}`); }

  const graph = {
    generatedAt: new Date().toISOString(),
    dataSource: "live",
    providers: { btc: "blockstream.info", eth: "eth.blockscout.com",
                 polygon: "polygon.blockscout.com", tron: "apilist.tronscanapi.com" },
    prices,
    nodes: [...nodeKeys].map((k) => {
      const i = k.indexOf(":");
      const chain = k.slice(0, i), address = k.slice(i + 1);
      let inUsd = 0, outUsd = 0, deg = 0;
      for (const a of agg.values()) {
        if (a.chain !== chain) continue;
        if (a.to === address) { inUsd += a.value_usd; deg++; }
        if (a.from === address) { outUsd += a.value_usd; deg++; }
      }
      return {
        id: k,
        type: targetAddrs.has(address) ? "target" : "wallet",
        data: {
          address, chain, label: short(address),
          hop: visited.get(k) ?? null,
          isTarget: targetAddrs.has(address),
          inUsd: +inUsd.toFixed(2), outUsd: +outUsd.toFixed(2), degree: deg,
          explorerUrl: explorerUrl(chain as Chain, address),
        },
      };
    }),
    edges: [...agg.values()].map((a, i) => ({
      id: `e${i}`, source: `${a.chain}:${a.from}`, target: `${a.chain}:${a.to}`,
      label: fmt(a.value_usd), animated: a.value_usd > 10_000,
      data: { chain: a.chain, valueUsd: +a.value_usd.toFixed(2),
              txCount: a.count, txHashes: a.hashes },
    })),
  };
  await Deno.writeTextFile(outFile, JSON.stringify(graph, null, 2));
  console.log(`\nReact Flow graph -> ${outFile} ` +
              `(${graph.nodes.length} nodes, ${graph.edges.length} edges)`);
}

console.log("\n" + "=".repeat(72));
console.log("All data above was fetched live. Nothing here is mock.");
console.log("=".repeat(72));
