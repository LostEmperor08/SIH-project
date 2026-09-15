# Chakravyuh SETU — Agent Rules

Live cryptocurrency fraud attribution platform for SIH PS 26183 (MHA / I4C).
An investigation tool used by law-enforcement officers. Output from it can
contribute to freezing someone's assets, so correctness and honesty about
uncertainty matter more than feature velocity.

---

## Workspace

```
backend/    FastAPI gateway — auth, /trace, providers          (Python 3.10+)
aiml/       ML layer — 4 models + SHAP explanations            (Python)
supabase/   migrations/ (01–07) + Deno edge functions          (SQL, TypeScript)
scripts/    verify-live.ts, parser regression tests            (Deno, Node)
frontend/   React + Vite + React Flow
docs/       LIVE_DATA.md, API_SOURCES.md, per-package READMEs
```

## Verify before claiming done

```bash
cd backend && python -m pytest tests/ -q     # must be 57 passed
cd aiml    && python -m tests.smoke_test     # must be 12/12
node scripts/tests/parsers.test.mjs          # must be 30 passed
```

Never report a task complete without running the suite that covers it.
"It should work" is not a result.

---

## Hard rules

### 1. Never introduce mock or placeholder data
The system fails closed by design. If a provider is unreachable, return the
error — `/trace` responds 404 with `providerErrors` attached. Do not add a
fallback that invents transactions, wallets, or risk scores. A fabricated
edge in an investigation graph is worse than an empty screen.

### 2. Never weaken the security controls
`backend/app/security.py` implements nine controls documented in
`docs/BACKEND.md`. Specifically, do not:
- add a development bypass that invents an officer identity
- let an unreachable auth service result in anything but 503
- compare secrets with `==` (use `hmac.compare_digest`)
- read the officer's role from a JWT claim — it comes from `user_roles`
- allow `cors_origins="*"` in production
- permit an officer to review their own dossier

`backend/tests/test_security.py` enforces all of this. If a change makes
those tests fail, the change is wrong, not the tests.

### 3. The audit log is append-only and hash-chained
Every writer and the verifier call the **single shared** `audit_hash()` in
`supabase/migrations/03_audit_evidence.sql`. Do not write a bespoke hash
anywhere. This already broke once: `append_audit` omitted the `before_data`
segment the verifier expected, so every RPC-written row read as `TAMPERED`.
A tamper-evident log that cries wolf is worse than no log.

After any change touching audit code, run:
```sql
SELECT * FROM verify_audit_chain();   -- must return ok = true
```

### 4. Provider gotchas — do not reintroduce these
Both were found by querying the live APIs, and both are locked down by
`scripts/tests/parsers.test.mjs`.

- **Blockscout:** the `filter` parameter accepts `to` **or** `from` only.
  `filter=to | from` returns HTTP 422. Send **no** filter — unfiltered
  already returns both directions.
- **Blockstream:** mempool transactions arrive as `status:{confirmed:false}`
  with **no** `block_time`. They are excluded by default. Never fall back to
  `now()` for a missing block time — that records an unconfirmed transfer as
  settled, and an unconfirmed tx can be RBF-replaced and never happen.
- **BSC** has no keyless explorer left. It needs `ETHERSCAN_API_KEY`
  (Etherscan V2, `chainid=56`). Fail with that message; never return an
  empty graph that reads as "no activity".
- **Tron:** only value TRX and USD stablecoins. Multiplying an arbitrary
  TRC20 by the TRX price is nonsense — leave it `value_usd: 0` and set
  `raw.unvalued`.

### 5. The ML feature schema is a contract
`aiml/src/features/schema.py` is imported by **both** training and serving.
That is the only defence against training/serving skew — where a model
scores 0.95 offline and produces garbage in production because the serving
path built column 17 differently. To add a feature: add it to `FEATURES`,
compute it in `extract.py::_compute`, retrain. Never compute a feature in
one place only.

### 6. Do not quote synthetic metrics as accuracy
`--source synthetic` generates wallets from the same patterns the label
functions detect. Its AUC-PR of 1.000 is circular by construction and must
never appear in a report or presentation. Real numbers come from
`python -m src.train --source elliptic`.

### 7. Abstention is a valid answer
`VASPModel` returns `unknown` below 0.55 confidence. Do not "improve" this
by always emitting a best guess. Telling an officer "this is Binance" when
it is not sends the freeze request to the wrong VASP and burns the only
chance to recover the funds.

### 8. Degradation is designed, not accidental
| Failure | Behaviour |
|---|---|
| ML service down | SQL rules, `scoringMode: "rules_only"` |
| Persistence fails | still return the graph, append to `providerErrors` |
| One provider errors | other chains continue |
| Price lookup fails | reuse last known price |
| **Auth unreachable** | **503 — the one thing that must not degrade** |

Do not "fix" a degradation path by making it raise, and do not add a new
one that silently swallows an error without surfacing it in the response.

---

## Conventions

**Python** — 4 spaces, type hints on public functions, `from __future__
import annotations` at the top. Comments explain *why*, never *what*. No
comment restating the line below it.

**SQL** — lowercase keywords, 2-space indent. Every new table gets RLS
`enable` **and** `force`, plus explicit policies. Default-deny: no policy
means no access. `SECURITY DEFINER` functions must pin `set search_path`.

**TypeScript** — the edge functions are Deno, not Node. Imports are URLs
(`https://esm.sh/...`). No `npm install` in `supabase/functions/`.

**Secrets** — environment only. Never a literal key in code, tests, or a
committed `.env`. `.env.example` carries empty placeholders.

**Errors** — never leak a traceback to a client. `main.py` returns
`{ok:false, error, requestId}`; the detail goes to the server log.

---

## Adding things

**A new chain:** add the regex to `backend/app/schemas.py::ADDRESS_PATTERNS`,
an adapter in `backend/app/providers/adapters.py`, a case in
`address_history()`, entries in `NATIVE` / `explorer_url` / `tx_explorer_url`,
the enum value in `supabase/migrations/01_schema.sql`, and a parser test.

**A new endpoint:** router in `backend/app/routers/`, Pydantic models in
`schemas.py`, a role dependency, a rate-limit bucket, an `append_audit` call
if it touches case data, and tests.

**A new model:** class in `aiml/src/models/classifiers.py` with the same
`fit / predict_proba` surface, a stage in `train.py`, registry save with a
`Manifest`, and load in `serving/inference.py`.

---

## Before a demo

1. `make test` — all three suites green
2. `SELECT * FROM verify_audit_chain();` → `chain intact`
3. `deno run --allow-net --allow-env scripts/verify-live.ts btc:<addr> --hops 2`
4. Order matters: trace real addresses → train on them → set `ML_API_URL`
5. Confirm `/trace` returns `scoringMode: "ml"`, not `"rules_only"`
6. `ENVIRONMENT=production` disables `/docs` and refuses CORS `*`

## Tone in reports and presentations

State limits plainly. In-memory rate limiting is per-process. USD figures
are current spot rate, not historical cost basis. Weak-supervision labels
are weaker evidence than an OFAC hit, and the API says which is which.
Being straight about this is worth more than a big number — and it is the
question a judge is most likely to ask.
