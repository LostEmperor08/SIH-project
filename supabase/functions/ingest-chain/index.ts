// =====================================================================
// ingest-chain — LIVE blockchain ingestion
//
// Bitcoin  : Blockstream Esplora  (no API key)     https://blockstream.info/api
// Ethereum : Blockscout v2        (no API key)     https://eth.blockscout.com/api/v2
//
// POST body: { "chain": "btc" | "eth", "blocks": 3, "address": "optional" }
//   - no address  -> ingest the latest N blocks (live firehose)
//   - address     -> ingest that address's full recent history (targeted trace)
//
// After writing, it calls run_detection_pipeline() so scores and alerts
// appear immediately; Realtime pushes them to the browser.
// =====================================================================
import { admin, chunk, CORS, HttpError, json, safeFetch, usdPrice } from "../_shared/lib.ts";

const BTC_API = Deno.env.get("BTC_API") ?? "https://blockstream.info/api";
const ETH_API = Deno.env.get("ETH_API") ?? "https://eth.blockscout.com/api/v2";

type Edge = {
  chain: string; tx_hash: string; vout_index: number;
  block_height: number | null; block_time: string;
  from_address: string; to_address: string;
  value_native: number; value_usd: number; fee_usd: number;
  asset: string; raw: Record<string, unknown>;
};

// ---------------------------------------------------------------------
// BITCOIN — Esplora
// ---------------------------------------------------------------------
async function btcTxToEdges(tx: any, px: number): Promise<Edge[]> {
  const inputs: string[] = (tx.vin ?? [])
    .map((v: any) => v?.prevout?.scriptpubkey_address).filter(Boolean);
  if (inputs.length === 0) return [];                       // coinbase
  const primary = inputs[0];
  const time = new Date((tx.status?.block_time ?? Date.now() / 1000) * 1000).toISOString();
  const feeBtc = (tx.fee ?? 0) / 1e8;

  return (tx.vout ?? [])
    .map((o: any, i: number) => {
      const to = o?.scriptpubkey_address;
      if (!to || to === primary) return null;               // skip change-to-self
      const v = (o.value ?? 0) / 1e8;
      return {
        chain: "btc", tx_hash: tx.txid, vout_index: i,
        block_height: tx.status?.block_height ?? null, block_time: time,
        from_address: primary, to_address: to,
        value_native: v, value_usd: +(v * px).toFixed(2),
        fee_usd: +(feeBtc * px).toFixed(2), asset: "BTC",
        // `inputs` is what the common-input-ownership clustering reads
        raw: { inputs, outputCount: tx.vout.length, inputCount: inputs.length, size: tx.size },
      } as Edge;
    })
    .filter(Boolean) as Edge[];
}

async function ingestBtcBlocks(n: number): Promise<Edge[]> {
  const px = await usdPrice("bitcoin");
  const tipHash = await (await safeFetch(`${BTC_API}/blocks/tip/hash`)).text();
  let hash = tipHash.trim();
  const edges: Edge[] = [];

  for (let b = 0; b < n; b++) {
    // Esplora paginates block txs 25 at a time
    for (let start = 0; start < 75; start += 25) {
      const res = await safeFetch(`${BTC_API}/block/${hash}/txs/${start}`);
      const txs = await res.json();
      if (!Array.isArray(txs) || txs.length === 0) break;
      for (const tx of txs) edges.push(...await btcTxToEdges(tx, px));
      if (txs.length < 25) break;
    }
    const hdr = await (await safeFetch(`${BTC_API}/block/${hash}`)).json();
    if (!hdr.previousblockhash) break;
    hash = hdr.previousblockhash;
  }
  return edges;
}

async function ingestBtcAddress(addr: string): Promise<Edge[]> {
  const px = await usdPrice("bitcoin");
  const txs = await (await safeFetch(`${BTC_API}/address/${addr}/txs`)).json();
  const edges: Edge[] = [];
  for (const tx of txs) edges.push(...await btcTxToEdges(tx, px));
  return edges;
}

// ---------------------------------------------------------------------
// ETHEREUM — Blockscout v2
// ---------------------------------------------------------------------
function ethTxToEdge(tx: any, px: number): Edge | null {
  const from = tx.from?.hash?.toLowerCase();
  const to = tx.to?.hash?.toLowerCase();
  if (!from || !to) return null;                            // contract creation
  const v = Number(tx.value ?? 0) / 1e18;
  const gasUsd = (Number(tx.gas_used ?? 0) * Number(tx.gas_price ?? 0)) / 1e18 * px;
  return {
    chain: "eth", tx_hash: tx.hash, vout_index: 0,
    block_height: tx.block_number ?? tx.block ?? null,
    block_time: tx.timestamp ?? new Date().toISOString(),
    from_address: from, to_address: to,
    value_native: v, value_usd: +(v * px).toFixed(2),
    fee_usd: +gasUsd.toFixed(2), asset: "ETH",
    raw: { method: tx.method, status: tx.status, txTypes: tx.tx_types },
  };
}

async function ingestEthBlocks(n: number): Promise<Edge[]> {
  const px = await usdPrice("ethereum");
  const stats = await (await safeFetch(`${ETH_API}/blocks?type=block`)).json();
  const tip = stats.items?.[0]?.height;
  if (!tip) throw new HttpError(502, "could not read Ethereum tip height");
  const edges: Edge[] = [];
  for (let h = tip; h > tip - n; h--) {
    const res = await safeFetch(`${ETH_API}/blocks/${h}/transactions`);
    const { items = [] } = await res.json();
    for (const tx of items) {
      const e = ethTxToEdge(tx, px);
      if (e && e.value_native > 0) edges.push(e);
    }
  }
  return edges;
}

async function ingestEthAddress(addr: string): Promise<Edge[]> {
  const px = await usdPrice("ethereum");
  // No `filter` param: Blockscout accepts only "to" OR "from" and returns
  // HTTP 422 for "to | from". Unfiltered gives both directions anyway.
  const res = await safeFetch(`${ETH_API}/addresses/${addr}/transactions`);
  const { items = [] } = await res.json();
  return items.map((t: any) => ethTxToEdge(t, px)).filter(Boolean) as Edge[];
}

// ---------------------------------------------------------------------
// PERSIST
// ---------------------------------------------------------------------
async function persist(edges: Edge[], chain: string) {
  const sb = admin();
  if (edges.length === 0) return { wallets: 0, transactions: 0 };

  // 1. upsert wallets (vertices) first — FK-free but keeps the graph whole
  const addrs = [...new Set(edges.flatMap((e) => [e.from_address, e.to_address]))];
  const walletRows = addrs.map((a) => ({ chain, address: a }));
  for (const c of chunk(walletRows, 500)) {
    await sb.from("wallets").upsert(c, { onConflict: "chain,address", ignoreDuplicates: true });
  }

  // 2. insert edges, de-duplicating on the natural key
  let inserted = 0;
  for (const c of chunk(edges, 500)) {
    const { error, count } = await sb.from("transactions")
      .upsert(c, { onConflict: "chain,tx_hash,vout_index,from_address,to_address",
                   ignoreDuplicates: true, count: "exact" });
    if (error) console.error("tx upsert:", error.message);
    inserted += count ?? 0;
  }

  // 3. refresh wallet aggregates from the edges we just wrote
  await sb.rpc("refresh_wallet_stats", { p_chain: chain });

  return { wallets: addrs.length, transactions: inserted };
}

// ---------------------------------------------------------------------
Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  try {
    const { chain = "btc", blocks = 2, address = null } =
      req.method === "POST" ? await req.json().catch(() => ({})) : {};

    if (!["btc", "eth"].includes(chain)) throw new HttpError(400, "chain must be btc or eth");
    const t0 = Date.now();

    let edges: Edge[];
    if (address) {
      edges = chain === "btc" ? await ingestBtcAddress(address) : await ingestEthAddress(address);
    } else {
      edges = chain === "btc"
        ? await ingestBtcBlocks(Math.min(blocks, 5))
        : await ingestEthBlocks(Math.min(blocks, 10));
    }

    const stats = await persist(edges, chain);

    // run detection immediately so the dashboard is never stale
    const sb = admin();
    const { data: pipeline } = await sb.rpc("run_detection_pipeline", { p_chain: chain });

    return json({
      ok: true, chain, mode: address ? "targeted" : "firehose",
      edgesFetched: edges.length, ...stats, pipeline,
      elapsedMs: Date.now() - t0, source: chain === "btc" ? BTC_API : ETH_API,
    });
  } catch (e) {
    const status = e instanceof HttpError ? e.status : 500;
    console.error(e);
    return json({ ok: false, error: String(e.message ?? e) }, status);
  }
});
