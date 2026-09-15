# API Sources Used in the SKV Backend

Every external API called by the code, what it provides, and exactly where it is called.
All five are free and none except CoinGecko has any rate limit worth worrying about at
demo scale. **No API key is required for any of them.**

---

## 1. Blockstream Esplora API — Bitcoin

| | |
|---|---|
| **Base URL** | `https://blockstream.info/api` |
| **Docs** | https://github.com/Blockstream/esplora/blob/master/API.md |
| **Auth** | None |
| **Used in** | `supabase/functions/ingest-chain/index.ts` → `ingestBtcBlocks()`, `ingestBtcAddress()` |
| **Configurable via** | `BTC_API` env var |

### Endpoints called

| Endpoint | Purpose in our code |
|---|---|
| `GET /blocks/tip/hash` | Find the current chain tip — the starting point for the live firehose |
| `GET /block/{hash}` | Read the block header to get `previousblockhash` and walk backwards N blocks |
| `GET /block/{hash}/txs/{start}` | Page through that block's transactions, 25 at a time |
| `GET /address/{address}/txs` | Targeted mode — pull one address's full recent history when an analyst investigates it |

### Why this one

Esplora returns **`vin[].prevout.scriptpubkey_address`** — the addresses that funded each
input. That field is what makes the common-input-ownership clustering possible; most
lightweight Bitcoin APIs omit it. We store the full input list in `transactions.raw.inputs`,
and `cluster-attribute` reads it back to union those addresses into one entity.

**Drop-in alternative if rate-limited:** [mempool.space](https://mempool.space/docs/api/rest)
runs the identical Esplora API — just set `BTC_API=https://mempool.space/api`.

---

## 2. Blockscout v2 API — Ethereum

| | |
|---|---|
| **Base URL** | `https://eth.blockscout.com/api/v2` |
| **Docs** | https://eth.blockscout.com/api-docs |
| **Auth** | None |
| **Used in** | `supabase/functions/ingest-chain/index.ts` → `ingestEthBlocks()`, `ingestEthAddress()` |
| **Configurable via** | `ETH_API` env var |

### Endpoints called

| Endpoint | Purpose in our code |
|---|---|
| `GET /blocks?type=block` | Read the latest block height (the tip) |
| `GET /blocks/{height}/transactions` | Pull every transaction in that block |
| `GET /addresses/{address}/transactions?filter=to \| from` | Targeted mode — one address's history, both directions |

### Fields we consume

`from.hash`, `to.hash`, `value` (wei → ETH ÷ 1e18), `hash`, `timestamp`, `block_number`,
`gas_used`, `gas_price`, `method`, `status`.

### Why this one

Blockscout is fully open-source and keyless, unlike Etherscan which now requires a key
per chain. Contract-creation transactions have a null `to` and are skipped; zero-value
transactions are filtered out since they carry no fund-flow signal.

**Alternatives:** Routescan, or Etherscan V2 if you want to register a key.

---

## 3. OFAC Sanctioned Digital Currency Addresses — Threat intelligence

| | |
|---|---|
| **Base URL** | `https://raw.githubusercontent.com/0xB10C/ofac-sanctioned-digital-currency-addresses/lists` |
| **Repo** | https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses |
| **Auth** | None |
| **Used in** | `supabase/functions/sync-threat-intel/index.ts` → `syncOfac()` |

### Files fetched

| File | Mapped to chain |
|---|---|
| `sanctioned_addresses_XBT.json` | `btc` |
| `sanctioned_addresses_ETH.json` | `eth` |
| `sanctioned_addresses_USDT_TRON.json` | `tron` |
| `sanctioned_addresses_BSC.json` | `bsc` |

Each file is a plain JSON array of address strings. We upsert them into `threat_intel`
with `source = 'OFAC_SDN'`, `severity = 100`, then `apply_threat_intel()` flags any
matching wallet as `is_sanctioned`.

### What this actually is

It is an **automatically regenerated extraction** of the digital-currency addresses
embedded in the US Treasury's Specially Designated Nationals (SDN) list — the same list
every regulated exchange screens against. The repo parses Treasury's published SDN XML
and commits the extracted addresses to the `lists` branch.

**Authoritative source of truth:** https://sanctionssearch.ofac.treas.gov/ — this is the
URL we store in `threat_intel.reference_url` and surface in alerts, so every sanctions
hit cites the official register rather than the mirror. See also
[OFAC FAQ 563](https://ofac.treasury.gov/faqs/563) on digital currency addresses in the SDN List.

> Say this to a judge: *"We screen against the actual OFAC SDN crypto address list,
> refreshed hourly, and every alert cites Treasury's own sanctions register."*

---

## 4. CoinGecko Simple Price API — USD valuation

| | |
|---|---|
| **Endpoint** | `GET https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=usd` |
| **Auth** | None (free tier) |
| **Used in** | `supabase/functions/_shared/lib.ts` → `usdPrice()` |

Converts native amounts (BTC, ETH) into USD so risk thresholds, structuring detection
($8k–$10k band) and volume metrics are all comparable across chains.

**Rate-limit handling:** results are cached in memory for 60 seconds, and on failure the
last known price is reused rather than throwing — a price hiccup must never stall ingestion.

---

## 5. Optional community threat feed

| | |
|---|---|
| **Endpoint** | Whatever you set in `THREAT_FEED_URL` |
| **Used in** | `sync-threat-intel/index.ts` → `syncCustomFeed()` |

Accepts any JSON array of `{ address, chain, category, name, severity, url }`. Point it at
a scam-address feed (Chainabuse-style exports, CryptoScamDB dumps, or your own curated
list) and those addresses flow into the same `threat_intel` table and scoring path as OFAC.
Left unset, it is silently skipped.

---

## Internal APIs (your own, not external)

These are what the frontend actually calls — the browser never touches a blockchain API directly.

| Call | Type | Returns |
|---|---|---|
| `supabase.rpc('api_dashboard')` | Postgres RPC | metrics, top-risk wallets, alerts, entity breakdown, 24h volume series |
| `supabase.rpc('api_investigate', {...})` | Postgres RPC | wallet + graph nodes/edges + cluster + sanction paths + alerts |
| `supabase.rpc('trace_funds', {...})` | Postgres RPC | multi-hop fund trace with taint share per path |
| `supabase.rpc('verify_evidence_chain', {...})` | Postgres RPC | per-item INTACT / TAMPERED verdict |
| `supabase.rpc('verify_audit_chain')` | Postgres RPC | whole-log integrity check |
| `supabase.functions.invoke('ingest-chain')` | Edge Function | triggers a live pull |
| `supabase.functions.invoke('cluster-attribute')` | Edge Function | re-runs clustering + VASP attribution |
| `supabase.functions.invoke('sync-threat-intel')` | Edge Function | refreshes sanctions |
| Realtime channel `skv-live` | Websocket | pushes every new transaction, alert and risk score to the browser |

---

## Reliability engineering around these APIs

All external calls go through `safeFetch()` in `_shared/lib.ts`:

- 15-second timeout via `AbortController`
- 3 retries with exponential backoff plus jitter
- HTTP 429 and 5xx treated as retryable; 4xx fails fast
- Price lookups degrade gracefully to the last cached value

This matters in a demo: a single upstream hiccup on stage does not blank your dashboard.

---

## Sources

- [Blockstream Esplora API reference](https://github.com/Blockstream/esplora/blob/master/API.md)
- [mempool.space REST API](https://mempool.space/docs/api/rest)
- [Blockscout Ethereum API docs](https://eth.blockscout.com/api-docs)
- [Blockscout open-source block explorer (ethereum.org)](https://ethereum.org/developers/tools/blockscout-open-source-block-explorer/)
- [0xB10C/ofac-sanctioned-digital-currency-addresses](https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses)
- [OFAC Sanctions List Search](https://sanctionssearch.ofac.treas.gov/)
- [OFAC FAQ 563 — digital currency addresses on the SDN List](https://ofac.treasury.gov/faqs/563)
- [Block explorer APIs compared 2026](https://eco.com/support/en/articles/14895612-block-explorer-apis-compared-2026-etherscan-blockscout-routescan-helius)
