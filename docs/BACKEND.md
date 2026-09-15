# Chakravyuh SETU — FastAPI Backend

The authenticated live provider gateway from §3–§5 of the project report.
Implements every endpoint in §4 and all nine security controls in §5.

```
React/Vite  ──JWT──▶  FastAPI (this)  ──▶  Blockstream / Blockscout / TronScan / Etherscan
                          │
                          ├──▶  Supabase  (RLS, audit, dossiers, persistence)
                          └──▶  ML service /ml/score  (falls back to SQL rules)
```

**Verified, not asserted:** 57 pytest tests pass, all 8 SQL migrations apply
to a real PostgreSQL 16 instance, and the RPC authorization logic is tested
against live Postgres including separation of duties.

---

## 1. Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in SUPABASE_URL and the keys
uvicorn main:app --reload --port 8000

curl localhost:8000/health
```

Apply the SQL in order — `01`–`06` from the other packages, then:

```sql
-- sql/07_officer_audit_dossier.sql
```

which adds `append_audit`, `review_dossier`, `is_active_officer`, the
`dossiers` and `watchlist` tables, and officer-scoped RLS.

```bash
pytest tests/ -v              # 57 passed
```

---

## 2. Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | public | Liveness. Booleans only — leaks no URLs, keys or versions |
| POST | `/trace` | analyst+ | Live multi-hop blockchain trace → React Flow graph |
| GET | `/graph/{chain}/{address}` | viewer+ | Re-read an already-ingested graph. No provider calls |
| POST | `/threat-intel/sync` | investigator+ | Refresh the OFAC cache |
| POST | `/dossier/review` | admin | Approve / reject / return a dossier |
| `/ml/*` | | analyst+ | Mounted automatically when `chakravyuh-aiml` is importable |

### POST /trace

```json
{
  "targets": [
    { "chain": "btc", "address": "bc1q..." },
    { "chain": "eth", "address": "0x..." }
  ],
  "hops": 2,
  "cap_per_address": 50,
  "include_unconfirmed": false,
  "score": true,
  "persist": true
}
```

Returns `graph.nodes` / `graph.edges` ready for React Flow. Each node carries
`riskScore`, `riskBand`, `entity`, `sanctioned`, `hopsToExchange`,
`narrative`, `recommendedActions`, `explorerUrl`. Each edge carries
`valueUsd`, `txCount`, `txHashes`, `explorerUrls` — every line on the graph
clicks through to the real block explorer.

```tsx
const { graph } = await api.post("/trace", { targets, hops: 2 });
<ReactFlow nodes={graph.nodes} edges={graph.edges} />
```

**No mock path.** If the providers return nothing, `/trace` responds 404 with
the provider errors attached. It never substitutes placeholder edges.

---

## 3. The nine security controls, and where each lives

| # | Control | Implementation | Test |
|---|---|---|---|
| 1 | Fail-closed auth | `security.py` — no dev bypass; an unreachable auth service returns 503, never a pass | `TestFailClosedAuth` (6) |
| 2 | Supabase bearer verification | `/auth/v1/user` round trip, 60s cache | `test_no_mock_identity_fallback` |
| 3 | Service key, constant time | `hmac.compare_digest`; keys under 32 chars refused as unconfigured | `TestServiceKey` (4, incl. AST check) |
| 4 | Per-identity rate limiting | Sliding window, per bucket (`trace` 10/min, `ti` 5/5min) | `TestRateLimiting` (5) |
| 5 | Chain allowlist + validation | `schemas.py` — per-chain regex before any network call | `TestValidation` (10) |
| 6 | Restricted CORS | `main.py`; `*` raises at startup in production | `TestCORS` (3) |
| 7 | Active-officer check | `is_active_officer()` in SQL + role lookup at auth time | SQL test 11 |
| 8 | Admin-only dossier review | API dependency **and** `review_dossier` RPC | `TestRoles` (5) + SQL tests 5–9 |
| 9 | Server-derived audit identity | `append_audit` takes no actor parameter — `auth.uid()` inside | SQL tests 1–3 |

Two details worth saying out loud in a viva:

**Role comes from the database, never the token.** A JWT claim saying
`role: admin` is ignored; the role is read from `user_roles` on every
verification. A client-supplied role claim is an escalation waiting to happen.

**Separation of duties on dossiers.** An officer cannot approve their own
dossier *even if they hold the admin role*. Enforced in `review_dossier`,
verified by SQL test 6.

---

## 4. Three real bugs this work found

**The audit chain reported tampering on legitimate rows.** `append_audit`
hashed `(prev, time, actor, action, resource, pk, detail)` while
`verify_audit_chain` recomputed over `(…, before_data, after_data)` — a
missing segment, so every RPC-written row verified as `TAMPERED`. A
tamper-evident log that cries wolf is worse than no log: nobody believes the
alarm when it matters. Fixed by extracting one shared `audit_hash()` that
every writer and the verifier call, so the formats cannot drift again. The
verifier also no longer exempts `READ` rows — an exempt row type is a place
to hide a forged entry. Now: **15 rows, chain intact.**

**Blockscout `filter=to | from` returns HTTP 422.** The API accepts only
`to` *or* `from`. Your existing `ingest-chain` had that syntax, so every
targeted Ethereum trace was silently failing. Unfiltered returns both
directions, which is what a trace needs.

**Blockstream mempool transactions have no `block_time`.** They arrive as
`status: {confirmed: false}` with no timestamp; the old fallback dated them
`now()`, recording an unconfirmed transfer as settled. An unconfirmed tx can
be RBF-replaced and never happen. Excluded by default now.

---

## 5. Degradation, on purpose

| If this fails | The API does | Why |
|---|---|---|
| ML service down | Falls back to SQL rules, reports `scoringMode: "rules_only"` | An officer with rule-based scores beats an officer with an error page — and the field says honestly which it is |
| Supabase persistence fails | Still returns the graph, appends to `providerErrors` | Persistence is not the deliverable; the trace is |
| One provider errors mid-trace | Other chains continue, error listed per address | A dead Tron endpoint must not kill a Bitcoin trace |
| Price lookup fails | Reuses last known price | A price hiccup must never stall an investigation |
| **Supabase Auth unreachable** | **503, request refused** | The one thing that does *not* degrade. An auth service you cannot reach is not permission to proceed |

---

## 6. Provider matrix

| Chain | Provider | Key |
|---|---|---|
| `btc` | Blockstream Esplora | none |
| `eth` | Blockscout v2 | none |
| `polygon` | Blockscout v2 | none |
| `tron` | TronScan | none |
| `bsc` | Etherscan V2 (`chainid=56`) | **free key required** |

Every keyless BSC explorer has closed — `bnb.blockscout.com` and
`bsc.blockscout.com` both 404, Routescan answers "chain not supported" for
56. One free key from etherscan.io covers BSC and all other EVM chains.
Without it BSC fails with that explanation rather than returning an empty
graph you might read as "no activity".

Non-TRX, non-stablecoin TRC20 transfers are recorded with `value_usd: 0` and
flagged `raw.unvalued` — multiplying an arbitrary token by the TRX price
would be worse than leaving it unvalued.

---

## 7. Layout

```
chakravyuh-backend/
├── main.py                      app factory, CORS, middleware, error handlers
├── app/
│   ├── config.py                settings; production refuses CORS '*'
│   ├── security.py              controls 1,2,3,4,7 + role dependencies
│   ├── schemas.py               control 5 — per-chain address regex
│   ├── providers/
│   │   ├── base.py              NormEdge, retry, concurrency gate, price cache
│   │   └── adapters.py          btc / blockscout / tron / bsc
│   ├── services/
│   │   ├── trace.py             multi-hop BFS + React Flow graph builder
│   │   └── supabase_svc.py      persistence, threat intel, audit, ML calls
│   └── routers/
│       ├── trace.py             POST /trace
│       └── misc.py              /health, /threat-intel/sync, /dossier/review, /graph
├── sql/07_officer_audit_dossier.sql
└── tests/                       57 tests
```

---

## 8. Known limits

- **Rate limiting is in-memory**, so it is per-process. Honest for a single
  instance; behind multiple workers you want Redis. Still worth having: it
  stops one runaway script exhausting the shared free-tier provider quota.
- **USD values are current spot rate** applied to all transfers, not
  historical cost basis. The response says so in `prices.note` — don't let
  anyone read those as value-at-time-of-transfer.
- **`max_hops` is 3.** A 4-hop trace from a busy address walks a meaningful
  fraction of the chain.
- Hop expansion is **highest-value-first** when the budget binds. Following
  the money is the investigative priority; an arbitrary slice would as
  likely follow dust.

---

## 9. Before the demo

- [ ] `pytest tests/ -v` → 57 passed
- [ ] Apply `sql/07_officer_audit_dossier.sql`
- [ ] `SELECT * FROM verify_audit_chain();` → `chain intact`
- [ ] Set `ETHERSCAN_API_KEY` if any address is on BSC
- [ ] Set `ENVIRONMENT=production` — this disables `/docs` and refuses CORS `*`
- [ ] Order matters: trace a few addresses → train the ML → set `ML_API_URL`
- [ ] Confirm `scoringMode` says `"ml"`, not `"rules_only"`

---

## Sources

- [Blockstream Esplora API](https://github.com/Blockstream/esplora/blob/master/API.md)
- [Blockscout address transactions — filter values](https://docs.blockscout.com/api-reference/addresses/list-transactions-involving-a-specific-address-with-to-from-filtering)
- [TronScan API](https://docs.tronscan.org/api-endpoints/transactions-and-transfers)
- [OFAC sanctioned digital currency addresses](https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses)
- [OFAC Sanctions List Search](https://sanctionssearch.ofac.treas.gov/)
