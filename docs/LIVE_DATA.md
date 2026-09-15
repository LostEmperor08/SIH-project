# Live Data — Chakravyuh SETU

How real transaction data reaches your transaction graph, and how to prove it
on your own addresses before the demo.

**There is no mock path.** If a provider is unreachable, the endpoint returns
HTTP 404/502 with the provider error. It never substitutes placeholder edges.

---

## 1. Prove it on your addresses in 30 seconds

No Supabase, no deployment, no ML service needed:

```bash
deno run --allow-net --allow-env scripts/verify-live.ts \
  btc:<your-btc-address> \
  eth:<your-eth-address> \
  --hops 2

# write a React Flow graph file too
deno run --allow-net --allow-env --allow-write scripts/verify-live.ts \
  btc:<addr> eth:<addr> --hops 2 --out graph.json
```

It prints spot prices, per-hop fetch results, inbound/outbound totals per
address, the largest transfers with their tx hashes, and a ranked
counterparty table — the high-fan-in two-way addresses there are your
candidate VASP endpoints.

Exit code `2` with "NO TRANSACTIONS FOUND" means the addresses are genuinely
unused or a provider is down. That is the fail-closed behaviour, not a bug.

---

## 2. The endpoint

`POST /functions/v1/investigate-address`

```json
{
  "targets": [
    { "chain": "btc",  "address": "bc1q..." },
    { "chain": "eth",  "address": "0x..." },
    { "chain": "tron", "address": "T..." }
  ],
  "hops": 2,
  "cap_per_address": 50,
  "score": true
}
```

Returns `{ ok, dataSource: "live", stats, prices, providerErrors, graph }`
where `graph.nodes` / `graph.edges` drop straight into React Flow:

```tsx
const res = await fetch(`${SUPABASE_URL}/functions/v1/investigate-address`, {
  method: "POST",
  headers: { Authorization: `Bearer ${session.access_token}`,
             "Content-Type": "application/json" },
  body: JSON.stringify({ targets, hops: 2 }),
});
const { graph } = await res.json();

<ReactFlow nodes={graph.nodes} edges={graph.edges} />
```

Each node carries `riskScore`, `riskBand`, `entity`, `sanctioned`,
`hopsToExchange`, `narrative`, `recommendedActions`, `explorerUrl`.
Each edge carries `valueUsd`, `txCount`, `txHashes`, `explorerUrls` —
so every line on your graph is clickable through to the real block explorer.
That is the detail that makes a judge believe the data is real.

Parallel transfers between the same pair are aggregated into one weighted
edge. A hundred separate lines between two nodes is unreadable; one line
labelled `$412,000 · 103 tx` is evidence.

---

## 3. Provider matrix (verified 15 Sep 2026)

| Chain | Provider | Key | Endpoint |
|---|---|---|---|
| `btc` | Blockstream Esplora | none | `blockstream.info/api/address/{a}/txs` |
| `eth` | Blockscout v2 | none | `eth.blockscout.com/api/v2/addresses/{a}/transactions` |
| `polygon` | Blockscout v2 | none | `polygon.blockscout.com/api/v2/...` |
| `tron` | TronScan | none | `apilist.tronscanapi.com/api/transfer?address={a}` |
| `bsc` | Etherscan V2 | **free key** | `api.etherscan.io/v2/api?chainid=56&...` |

BSC is the one exception. Every keyless BSC explorer has closed —
`bnb.blockscout.com` and `bsc.blockscout.com` both 404, and Routescan
answers `chain not supported` for 56. One free key from etherscan.io now
covers BSC *and* every other EVM chain through the V2 multichain endpoint:

```bash
supabase secrets set ETHERSCAN_API_KEY=your_free_key
```

Without it, a BSC request fails with that explanation rather than returning
an empty graph you might mistake for "no activity".

---

## 4. Two real bugs this work uncovered

Both were found by querying the live APIs, and both are locked down by
`tests/parsers.test.mjs` (30 assertions, all passing).

**Blockscout `filter=to | from` returns HTTP 422.** Several tutorials suggest
that syntax; the API accepts only `to` **or** `from`. The original
`ingest-chain` function had it, which means every targeted Ethereum trace was
silently failing. Fixed by dropping the parameter entirely — unfiltered
already returns both directions, which is what a trace needs.

**Blockstream mempool transactions have no `block_time`.** They come back as
`status: { confirmed: false }` with no `block_time` or `block_height`. The
original code fell back to `Date.now()`, which quietly dated an unconfirmed
transfer as if it had settled. An unconfirmed transaction can be RBF-replaced
or dropped and never happen at all — putting one in a dossier as a settled
fund movement is materially wrong. Mempool transactions are now **excluded by
default**; pass `"include_unconfirmed": true` to see them, and they arrive
flagged `raw.confirmed = false` with a null block height.

```bash
node tests/parsers.test.mjs      # 30 passed, 0 failed
```

---

## 5. Where the AI/ML fits

The edge function calls your FastAPI ML service:

```bash
supabase secrets set ML_API_URL=https://your-fastapi-host
supabase secrets set ML_API_KEY=...
```

Flow: trace → persist to `wallets`/`transactions` → `POST {ML_API_URL}/ml/score`
with the traced edges → write results to `ml_predictions` → merge into the
graph nodes.

**If `ML_API_URL` is unset or the service is down**, the function falls back
to `run_detection_pipeline()` — the deterministic SQL rules — and reports
`scoringMode: "rules_only"`. The graph still renders with scores. An officer
with rule-based scoring is far better served than an officer with an error
page, and `scoringMode` tells you honestly which one you are looking at.

The ML models themselves are in `chakravyuh-aiml/`. Before the demo, train on
real data rather than the synthetic smoke-test set:

```bash
cd chakravyuh-aiml
python -m src.train --source elliptic     # published benchmark numbers
python -m src.train --source supabase --chain btc   # your live ingested graph
uvicorn main:app                          # with ml_router mounted
```

The order matters: run `investigate-address` a few times first so there are
real wallets in Supabase, *then* train on them, *then* re-run the investigation
with `ML_API_URL` set. Training on an empty database produces nothing useful.

---

## 6. Limits and what they mean

| Limit | Value | Why |
|---|---|---|
| `hops` | max 3 | A 4-hop trace from a busy address walks a meaningful fraction of the chain and exceeds the function's execution budget |
| addresses per hop | 40 | Expanded **highest-value first** — following the money is the investigative priority; an arbitrary slice would just as likely follow dust |
| total edges | 8,000 | Response size and browser render limits |
| targets per request | 10 | Validated up front, so one bad address doesn't send nine good ones through a pointless trace |
| concurrent provider calls | 6 | The sweet spot for these free tiers; firing a whole hop at once gets you rate-limited into a failed demo |

USD values use the **current spot rate** applied to every transfer. Historical
cost basis would need a per-day price series. The response says so explicitly
in `prices.note` — don't let anyone read those figures as value-at-time-of-transfer.

---

## 7. Before the demo

- [ ] Run `verify-live.ts` on your four addresses — confirm real transfers come back
- [ ] `node tests/parsers.test.mjs` — 30/30
- [ ] Set `ETHERSCAN_API_KEY` if any address is on BSC
- [ ] Deploy: `supabase functions deploy investigate-address`
- [ ] Run `sync-threat-intel` once so OFAC screening is live
- [ ] Ingest, then train, then set `ML_API_URL` — in that order
- [ ] Check `scoringMode` in the response says `"ml"`, not `"rules_only"`

---

## Sources

- [Blockstream Esplora API](https://github.com/Blockstream/esplora/blob/master/API.md)
- [Blockscout address transactions endpoint + filter values](https://docs.blockscout.com/api-reference/addresses/list-transactions-involving-a-specific-address-with-to-from-filtering)
- [Blockscout filter format discussion #11617](https://github.com/orgs/blockscout/discussions/11617)
- [TronScan API — transactions and transfers](https://docs.tronscan.org/api-endpoints/transactions-and-transfers)
- [OFAC sanctioned digital currency addresses](https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses)
