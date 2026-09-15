// =====================================================================
// _shared/chains.ts — multi-chain address-history adapters
//
// One normalised shape out of five different providers. Every adapter
// returns NormEdge[] so the tracing logic never knows which chain it is
// walking.
//
// Provider matrix (verified 15 Sep 2026):
//   btc      Blockstream Esplora    no key   blockstream.info/api
//   eth      Blockscout v2          no key   eth.blockscout.com
//   polygon  Blockscout v2          no key   polygon.blockscout.com
//   tron     TronScan               no key   apilist.tronscanapi.com
//   bsc      Etherscan V2           FREE KEY api.etherscan.io/v2 (chainid=56)
//
// BSC is the odd one out: every keyless BSC explorer has closed. One free
// Etherscan key now covers all EVM chains via the V2 multichain endpoint,
// so set ETHERSCAN_API_KEY and BSC works; leave it unset and BSC requests
// fail with a clear message instead of silently returning nothing.
// =====================================================================

export type Chain = "btc" | "eth" | "polygon" | "tron" | "bsc";

export const CHAINS: Chain[] = ["btc", "eth", "polygon", "tron", "bsc"];

export interface NormEdge {
  chain: Chain;
  tx_hash: string;
  vout_index: number;
  block_height: number | null;
  block_time: string;        // ISO8601
  from_address: string;
  to_address: string;
  value_native: number;
  value_usd: number;
  fee_usd: number;
  asset: string;
  raw: Record<string, unknown>;
}

export class ChainError extends Error {
  constructor(public chain: Chain, msg: string) {
    super(`[${chain}] ${msg}`);
  }
}

// ---------------------------------------------------------------------
// Address validation — reject junk BEFORE spending an API call on it.
// Also stops an attacker using this endpoint as a blind SSRF/path probe.
// ---------------------------------------------------------------------
const PATTERNS: Record<Chain, RegExp> = {
  btc: /^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$/,
  eth: /^0x[a-fA-F0-9]{40}$/,
  polygon: /^0x[a-fA-F0-9]{40}$/,
  bsc: /^0x[a-fA-F0-9]{40}$/,
  tron: /^T[1-9A-HJ-NP-Za-km-z]{33}$/,
};

export function isValidAddress(chain: Chain, address: string): boolean {
  return PATTERNS[chain]?.test(address) ?? false;
}

export function normaliseAddress(chain: Chain, address: string): string {
  return chain === "btc" || chain === "tron" ? address.trim() : address.trim().toLowerCase();
}

// ---------------------------------------------------------------------
// Fetch with timeout, retry, backoff and a global concurrency gate.
//
// The gate matters more than it looks: a 3-hop BFS over a busy address
// fans out to hundreds of requests, and firing those at once gets you
// rate-limited into a failed demo. Six in flight is the sweet spot for
// the free tiers above.
// ---------------------------------------------------------------------
class Semaphore {
  private active = 0;
  private queue: (() => void)[] = [];
  constructor(private limit: number) {}

  async run<T>(fn: () => Promise<T>): Promise<T> {
    if (this.active >= this.limit) {
      await new Promise<void>((r) => this.queue.push(r));
    }
    this.active++;
    try {
      return await fn();
    } finally {
      this.active--;
      this.queue.shift()?.();
    }
  }
}

const gate = new Semaphore(Number(Deno.env.get("CHAIN_CONCURRENCY") ?? 6));

async function get(url: string, tries = 3): Promise<any> {
  return gate.run(async () => {
    for (let i = 0; i <= tries; i++) {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 15_000);
      try {
        const res = await fetch(url, {
          signal: ctl.signal,
          headers: { "Accept": "application/json", "User-Agent": "ChakravyuhSETU/1.0" },
        });
        clearTimeout(timer);
        if (res.status === 429 || res.status >= 500) throw new Error(`upstream ${res.status}`);
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 200)}`);
        return await res.json();
      } catch (e) {
        clearTimeout(timer);
        if (i === tries) throw e;
        await new Promise((r) => setTimeout(r, 500 * 2 ** i + Math.random() * 400));
      }
    }
  });
}

// ---------------------------------------------------------------------
// Price cache — 5 min. Historical USD valuation would need a per-day
// price series; for an investigation workspace the current rate applied
// consistently is the honest simplification, and it is labelled as such
// in the response so nobody mistakes it for historical cost basis.
// ---------------------------------------------------------------------
const NATIVE: Record<Chain, { id: string; symbol: string; decimals: number }> = {
  btc: { id: "bitcoin", symbol: "BTC", decimals: 8 },
  eth: { id: "ethereum", symbol: "ETH", decimals: 18 },
  polygon: { id: "matic-network", symbol: "POL", decimals: 18 },
  bsc: { id: "binancecoin", symbol: "BNB", decimals: 18 },
  tron: { id: "tron", symbol: "TRX", decimals: 6 },
};

const priceCache = new Map<string, { v: number; t: number }>();

export async function usdPrice(chain: Chain): Promise<number> {
  const { id } = NATIVE[chain];
  const hit = priceCache.get(id);
  if (hit && Date.now() - hit.t < 300_000) return hit.v;
  try {
    const j = await get(
      `https://api.coingecko.com/api/v3/simple/price?ids=${id}&vs_currencies=usd`);
    const v = Number(j?.[id]?.usd ?? 0);
    if (v > 0) priceCache.set(id, { v, t: Date.now() });
    return v || hit?.v || 0;
  } catch {
    return hit?.v ?? 0;
  }
}

// =====================================================================
// BITCOIN — Blockstream Esplora
// =====================================================================
async function btcHistory(
  address: string, px: number, cap: number, includeUnconfirmed = false,
): Promise<NormEdge[]> {
  const base = Deno.env.get("BTC_API") ?? "https://blockstream.info/api";
  const txs = await get(`${base}/address/${address}/txs`);
  if (!Array.isArray(txs)) return [];

  const edges: NormEdge[] = [];
  for (const tx of txs.slice(0, cap)) {
    // Esplora returns mempool transactions with status {confirmed:false} and
    // NO block_time/block_height. Treating one as a settled fund movement is
    // materially wrong in an investigation — it can be RBF-replaced or
    // dropped and never happen. Excluded unless explicitly requested.
    const confirmed = tx.status?.confirmed === true;
    if (!confirmed && !includeUnconfirmed) continue;

    const inputs: string[] = (tx.vin ?? [])
      .map((v: any) => v?.prevout?.scriptpubkey_address).filter(Boolean);
    if (inputs.length === 0) continue;                 // coinbase
    const primary = inputs[0];
    const ts = new Date((tx.status?.block_time ?? Date.now() / 1000) * 1000).toISOString();
    const feeBtc = (tx.fee ?? 0) / 1e8;

    (tx.vout ?? []).forEach((o: any, i: number) => {
      const to = o?.scriptpubkey_address;
      if (!to || to === primary) return;               // drop change-to-self
      const v = (o.value ?? 0) / 1e8;
      if (v <= 0) return;
      edges.push({
        chain: "btc", tx_hash: tx.txid, vout_index: i,
        block_height: tx.status?.block_height ?? null, block_time: ts,
        from_address: primary, to_address: to,
        value_native: v, value_usd: +(v * px).toFixed(2),
        fee_usd: +(feeBtc * px).toFixed(2), asset: "BTC",
        // inputs[] drives the common-input-ownership clustering
        raw: { inputs, inputCount: inputs.length, outputCount: tx.vout.length,
               confirmed },
      });
    });
  }
  return edges;
}

// =====================================================================
// EVM via Blockscout v2 — Ethereum, Polygon
// =====================================================================
const BLOCKSCOUT: Partial<Record<Chain, string>> = {
  eth: Deno.env.get("ETH_API") ?? "https://eth.blockscout.com/api/v2",
  polygon: Deno.env.get("POLYGON_API") ?? "https://polygon.blockscout.com/api/v2",
};

async function blockscoutHistory(
  chain: Chain, address: string, px: number, cap: number,
): Promise<NormEdge[]> {
  const base = BLOCKSCOUT[chain];
  if (!base) throw new ChainError(chain, "no Blockscout endpoint configured");

  // NO `filter` param. Blockscout's filter accepts exactly "to" OR "from";
  // passing "to | from" (as several tutorials suggest) returns HTTP 422.
  // Unfiltered already returns transactions in both directions, which is
  // what a trace needs.
  const j = await get(`${base}/addresses/${address}/transactions`);
  const items: any[] = j?.items ?? [];
  const dec = NATIVE[chain].decimals;

  return items.slice(0, cap).flatMap((tx) => {
    const from = tx.from?.hash?.toLowerCase();
    const to = tx.to?.hash?.toLowerCase();
    if (!from || !to) return [];                       // contract creation
    const v = Number(tx.value ?? 0) / 10 ** dec;
    if (v <= 0) return [];                             // pure contract call
    const gas = (Number(tx.gas_used ?? 0) * Number(tx.gas_price ?? 0)) / 10 ** dec;
    return [{
      chain, tx_hash: tx.hash, vout_index: 0,
      block_height: tx.block_number ?? tx.block ?? null,
      block_time: tx.timestamp ?? new Date().toISOString(),
      from_address: from, to_address: to,
      value_native: v, value_usd: +(v * px).toFixed(2),
      fee_usd: +(gas * px).toFixed(2), asset: NATIVE[chain].symbol,
      raw: { method: tx.method ?? null, status: tx.status ?? null },
    } as NormEdge];
  });
}

// =====================================================================
// TRON — TronScan
// =====================================================================
async function tronHistory(address: string, px: number, cap: number): Promise<NormEdge[]> {
  const base = Deno.env.get("TRON_API") ?? "https://apilist.tronscanapi.com";
  const key = Deno.env.get("TRONSCAN_API_KEY");
  const url = `${base}/api/transfer?address=${address}&limit=${Math.min(cap, 50)}&start=0&sort=-timestamp`;

  const j = await gate.run(async () => {
    const res = await fetch(url, {
      headers: key ? { "TRON-PRO-API-KEY": key, Accept: "application/json" }
                   : { Accept: "application/json" },
    });
    if (!res.ok) throw new ChainError("tron", `${res.status}`);
    return await res.json();
  });

  const data: any[] = j?.data ?? [];
  return data.slice(0, cap).flatMap((t) => {
    const from = t.transferFromAddress, to = t.transferToAddress;
    if (!from || !to) return [];
    // TRX has 6 decimals; TRC20 entries carry their own decimals
    const decimals = t.tokenInfo?.tokenDecimal ?? 6;
    const v = Number(t.amount ?? 0) / 10 ** decimals;
    if (v <= 0) return [];
    const isTrx = (t.tokenInfo?.tokenAbbr ?? "trx").toLowerCase() === "trx";
    return [{
      chain: "tron", tx_hash: t.transactionHash ?? t.hash ?? "", vout_index: 0,
      block_height: t.block ?? null,
      block_time: new Date(Number(t.timestamp ?? Date.now())).toISOString(),
      from_address: from, to_address: to,
      value_native: v,
      // only value native TRX; a stablecoin transfer is already USD-ish and
      // multiplying it by the TRX price would be nonsense
      value_usd: isTrx ? +(v * px).toFixed(2)
                       : +(v * (t.tokenInfo?.tokenAbbr?.match(/USD/i) ? 1 : 0)).toFixed(2),
      fee_usd: 0,
      asset: t.tokenInfo?.tokenAbbr ?? "TRX",
      raw: { confirmed: t.confirmed, contractRet: t.contractRet,
             tokenName: t.tokenInfo?.tokenName ?? null },
    } as NormEdge];
  });
}

// =====================================================================
// BSC — Etherscan V2 multichain (free key)
// =====================================================================
async function bscHistory(address: string, px: number, cap: number): Promise<NormEdge[]> {
  const key = Deno.env.get("ETHERSCAN_API_KEY");
  if (!key) {
    throw new ChainError(
      "bsc",
      "BSC requires ETHERSCAN_API_KEY. Every keyless BSC explorer has closed; " +
      "one free key at etherscan.io/apis covers BSC and all other EVM chains.",
    );
  }
  const url = `https://api.etherscan.io/v2/api?chainid=56&module=account&action=txlist` +
              `&address=${address}&page=1&offset=${Math.min(cap, 100)}&sort=desc&apikey=${key}`;
  const j = await get(url);
  if (j?.status === "0" && j?.message !== "No transactions found") {
    throw new ChainError("bsc", String(j?.result ?? j?.message));
  }
  const rows: any[] = Array.isArray(j?.result) ? j.result : [];

  return rows.flatMap((tx) => {
    const from = (tx.from ?? "").toLowerCase(), to = (tx.to ?? "").toLowerCase();
    if (!from || !to) return [];
    const v = Number(tx.value ?? 0) / 1e18;
    if (v <= 0) return [];
    const gas = (Number(tx.gasUsed ?? 0) * Number(tx.gasPrice ?? 0)) / 1e18;
    return [{
      chain: "bsc", tx_hash: tx.hash, vout_index: 0,
      block_height: Number(tx.blockNumber) || null,
      block_time: new Date(Number(tx.timeStamp) * 1000).toISOString(),
      from_address: from, to_address: to,
      value_native: v, value_usd: +(v * px).toFixed(2),
      fee_usd: +(gas * px).toFixed(2), asset: "BNB",
      raw: { isError: tx.isError, functionName: tx.functionName ?? null },
    } as NormEdge];
  });
}

// =====================================================================
// Public entry point
// =====================================================================
export async function addressHistory(
  chain: Chain, address: string, cap = 50, includeUnconfirmed = false,
): Promise<NormEdge[]> {
  if (!isValidAddress(chain, address)) {
    throw new ChainError(chain, `'${address}' is not a valid ${chain} address`);
  }
  const addr = normaliseAddress(chain, address);
  const px = await usdPrice(chain);

  switch (chain) {
    case "btc": return btcHistory(addr, px, cap, includeUnconfirmed);
    case "eth":
    case "polygon": return blockscoutHistory(chain, addr, px, cap);
    case "tron": return tronHistory(addr, px, cap);
    case "bsc": return bscHistory(addr, px, cap);
    default: throw new ChainError(chain, "unsupported chain");
  }
}

export function explorerUrl(chain: Chain, address: string): string {
  const m: Record<Chain, string> = {
    btc: `https://blockstream.info/address/${address}`,
    eth: `https://eth.blockscout.com/address/${address}`,
    polygon: `https://polygon.blockscout.com/address/${address}`,
    bsc: `https://bscscan.com/address/${address}`,
    tron: `https://tronscan.org/#/address/${address}`,
  };
  return m[chain];
}

export function txExplorerUrl(chain: Chain, hash: string): string {
  const m: Record<Chain, string> = {
    btc: `https://blockstream.info/tx/${hash}`,
    eth: `https://eth.blockscout.com/tx/${hash}`,
    polygon: `https://polygon.blockscout.com/tx/${hash}`,
    bsc: `https://bscscan.com/tx/${hash}`,
    tron: `https://tronscan.org/#/transaction/${hash}`,
  };
  return m[chain];
}
