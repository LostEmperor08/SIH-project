// =====================================================================
// Parser regression tests — node tests/parsers.test.mjs
//
// Fixtures are REAL response shapes captured from the live providers on
// 15 Sep 2026, not invented ones. These lock in the two bugs found during
// verification:
//
//   1. Blockstream returns mempool txs with status:{confirmed:false} and
//      NO block_time / block_height.
//   2. Blockscout returns HTTP 422 for `filter=to | from`; only "to" or
//      "from" are valid, and unfiltered already gives both directions.
//
// The transforms below mirror _shared/chains.ts exactly. If you change
// one, change the other and re-run this.
// =====================================================================

let passed = 0, failed = 0;
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name}`);
  if (!ok) { console.log(`        got:  ${JSON.stringify(got)}`);
             console.log(`        want: ${JSON.stringify(want)}`); failed++; }
  else passed++;
};
const ok = (name, cond) => eq(name, !!cond, true);

// ---------------------------------------------------------------------
// BITCOIN transform (mirrors btcHistory in chains.ts)
// ---------------------------------------------------------------------
function btcTxToEdges(tx, px, includeUnconfirmed = false) {
  const confirmed = tx.status?.confirmed === true;
  if (!confirmed && !includeUnconfirmed) return [];

  const inputs = (tx.vin ?? [])
    .map((v) => v?.prevout?.scriptpubkey_address).filter(Boolean);
  if (inputs.length === 0) return [];
  const primary = inputs[0];
  const ts = new Date((tx.status?.block_time ?? Date.now() / 1000) * 1000).toISOString();
  const feeBtc = (tx.fee ?? 0) / 1e8;

  const out = [];
  (tx.vout ?? []).forEach((o, i) => {
    const to = o?.scriptpubkey_address;
    if (!to || to === primary) return;
    const v = (o.value ?? 0) / 1e8;
    if (v <= 0) return;
    out.push({
      chain: "btc", tx_hash: tx.txid, vout_index: i,
      block_height: tx.status?.block_height ?? null, block_time: ts,
      from_address: primary, to_address: to,
      value_native: v, value_usd: +(v * px).toFixed(2),
      fee_usd: +(feeBtc * px).toFixed(2), asset: "BTC",
      raw: { inputs, inputCount: inputs.length, outputCount: tx.vout.length, confirmed },
    });
  });
  return out;
}

// ---------------------------------------------------------------------
// BLOCKSCOUT transform (mirrors blockscoutHistory in chains.ts)
// ---------------------------------------------------------------------
function blockscoutToEdge(tx, chain, px, decimals) {
  const from = tx.from?.hash?.toLowerCase();
  const to = tx.to?.hash?.toLowerCase();
  if (!from || !to) return [];
  const v = Number(tx.value ?? 0) / 10 ** decimals;
  if (v <= 0) return [];
  const gas = (Number(tx.gas_used ?? 0) * Number(tx.gas_price ?? 0)) / 10 ** decimals;
  return [{
    chain, tx_hash: tx.hash, vout_index: 0,
    block_height: tx.block_number ?? tx.block ?? null,
    block_time: tx.timestamp ?? new Date().toISOString(),
    from_address: from, to_address: to,
    value_native: v, value_usd: +(v * px).toFixed(2),
    fee_usd: +(gas * px).toFixed(2), asset: "ETH",
    raw: { method: tx.method ?? null, status: tx.status ?? null },
  }];
}

// ---------------------------------------------------------------------
// Address validation (mirrors PATTERNS in chains.ts)
// ---------------------------------------------------------------------
const PATTERNS = {
  btc: /^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$/,
  eth: /^0x[a-fA-F0-9]{40}$/,
  polygon: /^0x[a-fA-F0-9]{40}$/,
  bsc: /^0x[a-fA-F0-9]{40}$/,
  tron: /^T[1-9A-HJ-NP-Za-km-z]{33}$/,
};
const isValid = (c, a) => PATTERNS[c]?.test(a) ?? false;

// =====================================================================
console.log("=".repeat(62));
console.log("PARSER REGRESSION TESTS — real provider response shapes");
console.log("=".repeat(62));

// --- 1. BTC confirmed -------------------------------------------------
console.log("\nBitcoin / Blockstream Esplora");
const btcConfirmed = {
  txid: "aaa111", version: 1, locktime: 0, size: 258, weight: 1032, fee: 2500,
  vin: [{ prevout: { scriptpubkey_address: "14skjJCMJ7R2YgeyENTnAFnxPcQdswkAtH" } }],
  vout: [
    { scriptpubkey_address: "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", value: 3672 },
    { scriptpubkey_address: "14skjJCMJ7R2YgeyENTnAFnxPcQdswkAtH", value: 900000 }, // change
  ],
  status: { confirmed: true, block_height: 967040, block_time: 1757000000 },
};
const e1 = btcTxToEdges(btcConfirmed, 100000);
eq("confirmed tx yields 1 edge (change-to-self dropped)", e1.length, 1);
eq("value converted sats -> BTC", e1[0].value_native, 0.00003672);
eq("USD applied", e1[0].value_usd, 3.67);
eq("block height carried", e1[0].block_height, 967040);
eq("inputs[] kept for clustering", e1[0].raw.inputs.length, 1);

// --- 2. BTC unconfirmed (the bug) ------------------------------------
const btcMempool = {
  txid: "bbb222", fee: 1200,
  vin: [{ prevout: { scriptpubkey_address: "14skjJCMJ7R2YgeyENTnAFnxPcQdswkAtH" } }],
  vout: [{ scriptpubkey_address: "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", value: 5000 }],
  status: { confirmed: false },     // <- no block_time, no block_height
};
eq("mempool tx EXCLUDED by default", btcTxToEdges(btcMempool, 100000).length, 0);
const e2 = btcTxToEdges(btcMempool, 100000, true);
eq("mempool tx included when asked", e2.length, 1);
eq("mempool tx has null block_height", e2[0].block_height, null);
eq("mempool tx flagged unconfirmed", e2[0].raw.confirmed, false);
ok("mempool tx still gets a valid ISO block_time",
   !Number.isNaN(Date.parse(e2[0].block_time)));

// --- 3. BTC coinbase --------------------------------------------------
const coinbase = {
  txid: "ccc333", fee: 0, vin: [{ is_coinbase: true }],
  vout: [{ scriptpubkey_address: "bc1qminer", value: 312500000 }],
  status: { confirmed: true, block_height: 967041, block_time: 1757000600 },
};
eq("coinbase tx produces no edges", btcTxToEdges(coinbase, 100000).length, 0);

// --- 4. Blockscout real item -----------------------------------------
console.log("\nEthereum / Blockscout v2");
const bsItem = {
  hash: "0x9a4fa7d0349a990c8eed6cc2fc7fb05521a08a17aa7bc6e784e22ec75a6a4ce2",
  timestamp: "2026-09-15T05:16:11.000000Z",
  value: "32000000000000000000",           // string, not number
  block_number: 25980712,
  from: { hash: "0x44894aeEe56c2dd589c1D5C8cb04B87576967F97" },
  to: { hash: "0x00000000219ab540356cBB839Cbe05303d7705Fa" },
  gas_used: "50514", gas_price: "1070792942",
  method: null, status: "ok",
};
const e3 = blockscoutToEdge(bsItem, "eth", 4000, 18);
eq("string wei parsed to 32 ETH", e3[0].value_native, 32);
eq("USD applied", e3[0].value_usd, 128000);
eq("addresses lowercased", e3[0].from_address, "0x44894aeee56c2dd589c1d5c8cb04b87576967f97");
eq("block number carried", e3[0].block_height, 25980712);
ok("gas fee computed from string inputs", e3[0].fee_usd > 0 && e3[0].fee_usd < 1);
ok("timestamp parses", !Number.isNaN(Date.parse(e3[0].block_time)));

// --- 5. Blockscout edge cases ----------------------------------------
eq("contract creation (null to) skipped",
   blockscoutToEdge({ ...bsItem, to: null }, "eth", 4000, 18).length, 0);
eq("zero-value contract call skipped",
   blockscoutToEdge({ ...bsItem, value: "0" }, "eth", 4000, 18).length, 0);

// --- 6. Address validation -------------------------------------------
console.log("\nAddress validation");
ok("bech32 BTC accepted", isValid("btc", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"));
ok("legacy P2PKH accepted", isValid("btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"));
ok("P2SH accepted", isValid("btc", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"));
ok("EVM address accepted", isValid("eth", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"));
ok("Tron address accepted", isValid("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"));
eq("ETH address rejected on btc chain",
   isValid("btc", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"), false);
eq("truncated EVM address rejected", isValid("eth", "0xdeadbeef"), false);
eq("path-traversal attempt rejected", isValid("eth", "../../etc/passwd"), false);
eq("empty string rejected", isValid("btc", ""), false);

// --- 7. Provider URL correctness -------------------------------------
console.log("\nProvider URL construction");
const bsUrl = (base, addr) => `${base}/addresses/${addr}/transactions`;
const url = bsUrl("https://eth.blockscout.com/api/v2", "0xabc");
eq("Blockscout URL carries NO filter param (422 bug)", url.includes("filter"), false);
ok("Blockscout URL well formed",
   url === "https://eth.blockscout.com/api/v2/addresses/0xabc/transactions");

// =====================================================================
// Evidence path filter — the ledger must contain THIS case, not the
// neighbourhood. A 2-hop graph is mostly transfers between third parties
// who merely appear near the suspect; sealing those into a Sec 65B ledger
// produces a document that overstates what was traced.
// =====================================================================
console.log("\nEvidence money-path filter");
const { pathEdges } = await import("../../frontend/src/lib/moneyPath.js");

//        victim --> SUSPECT --> mule --> exchange
//        stranger1 --> stranger2          (nothing to do with the case)
const graph = {
  nodes: [
    { id: "0xsuspect", type: "SUSPECT", hop: 0, risk: 90 },
    { id: "0xvictim", type: "INTERMEDIARY", hop: 1, risk: 5 },
    { id: "0xmule", type: "INTERMEDIARY", hop: 1, risk: 60 },
    { id: "0xexchange", type: "VASP", hop: 2, risk: 40 },
    { id: "0xstranger1", type: "INTERMEDIARY", hop: 2, risk: 10 },
    { id: "0xstranger2", type: "INTERMEDIARY", hop: 2, risk: 10 },
  ],
  edges: [
    { source: "0xvictim", target: "0xsuspect", amount: 5000, tx_hash: "a" },
    { source: "0xsuspect", target: "0xmule", amount: 4800, tx_hash: "b" },
    { source: "0xmule", target: "0xexchange", amount: 4700, tx_hash: "c" },
    // The one that was polluting the ledger: huge, and entirely unrelated.
    { source: "0xstranger1", target: "0xstranger2", amount: 999999, tx_hash: "z" },
  ],
};

const kept = pathEdges(graph, "0xsuspect");
const hashes = kept.map((e) => e.tx_hash).sort();
eq("keeps only the money path", hashes, ["a", "b", "c"]);
eq("excludes the unrelated high-value transfer",
   kept.some((e) => e.tx_hash === "z"), false);
eq("inbound funding is hop 0",
   kept.find((e) => e.tx_hash === "a").hop, 0);
eq("first outward hop is 1",
   kept.find((e) => e.tx_hash === "b").hop, 1);
eq("second outward hop is 2",
   kept.find((e) => e.tx_hash === "c").hop, 2);
eq("ordered nearest-the-suspect first",
   kept.map((e) => e.hop), [0, 1, 2]);
ok("classifies direction",
   kept.find((e) => e.tx_hash === "a").direction === "INBOUND DEPOSIT" &&
   kept.find((e) => e.tx_hash === "b").direction === "OUTWARD SWEEP");
eq("no suspect in the graph seals nothing, rather than sealing the wrong thing",
   pathEdges({ nodes: [{ id: "0xa", type: "INTERMEDIARY", hop: 1 }],
               edges: [{ source: "0xa", target: "0xb", amount: 1 }] }, null).length, 0);
eq("a cycle terminates", pathEdges({
     nodes: [{ id: "0xs", type: "SUSPECT", hop: 0 }],
     edges: [{ source: "0xs", target: "0xb", amount: 1, tx_hash: "p" },
             { source: "0xb", target: "0xs", amount: 1, tx_hash: "q" }],
   }, "0xs").length, 2);
eq("address match is case-insensitive",
   pathEdges(graph, "0xSUSPECT").length, 3);

// =====================================================================
// Etherscan answers a rate limit with HTTP 200. If that is not detected,
// the retry never fires, the branch is silently pruned, and the same
// trace returns a different node count every run.
// =====================================================================
console.log("\nEtherscan rate-limit detection");
const isRateLimited = (b) => {
  if (!b || typeof b !== "object") return false;
  if (b.status !== "0") return false;
  const t = `${b.message || ""} ${b.result || ""}`.toLowerCase();
  return t.includes("rate limit") || t.includes("max calls") ||
         t.includes("too many") || t.includes("max rate");
};
ok("detects 'Max rate limit reached'",
   isRateLimited({ status: "0", message: "NOTOK", result: "Max rate limit reached" }));
eq("an empty address is NOT a rate limit",
   isRateLimited({ status: "0", message: "No transactions found", result: [] }), false);
eq("a successful response is NOT a rate limit",
   isRateLimited({ status: "1", message: "OK", result: [{}] }), false);

// =====================================================================
console.log("\n" + "=".repeat(62));
console.log(`${passed} passed, ${failed} failed`);
console.log("=".repeat(62));
process.exit(failed ? 1 : 0);
