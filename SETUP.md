# Setup Guide — Chakravyuh SETU

Three things this answers: how to set up Supabase, what `SERVICE_API_KEY`
is and how to make one, and what `ML_API_URL` / `ML_API_KEY` are for.

---

## Part 1 — Supabase

### 1.1 Create the project

1. Go to [supabase.com/dashboard](https://supabase.com/dashboard) → **New project**
2. Name it (e.g. `chakravyuh-setu`), pick a **strong database password** and
   save it in a password manager — you cannot see it again
3. Region: **South Asia (Mumbai)** — closest to you, so lower latency
4. Wait ~2 minutes for provisioning

### 1.2 Get your three keys

**Project Settings → API**

| What you see | Goes in | Safe in a browser? |
|---|---|---|
| Project URL | `SUPABASE_URL` and `VITE_SUPABASE_URL` | yes |
| `anon` `public` key | `SUPABASE_ANON_KEY` and `VITE_SUPABASE_ANON_KEY` | **yes** — designed for it |
| `service_role` `secret` key | `SUPABASE_SERVICE_ROLE_KEY` | **NEVER** |

The `service_role` key **bypasses every Row Level Security policy you
wrote**. It belongs in the backend `.env` only. If it ever reaches a browser
bundle or a git commit, rotate it immediately — anyone holding it can read
and write every case record you have.

The `anon` key is different: it is meant to ship to browsers, and RLS is what
protects your data behind it. That is why migration 08 matters.

### 1.3 Run the migrations — order matters

**SQL Editor → New query.** Paste and run each file in turn:

```
supabase-setup.sql            (your original schema)
supabase/migrations/01_schema.sql
supabase/migrations/02_rbac_rls.sql
supabase/migrations/03_audit_evidence.sql
supabase/migrations/04_detection_engine.sql
supabase/migrations/05_support_and_api.sql
supabase/migrations/06_ml_tables.sql
supabase/migrations/07_officer_audit_dossier.sql
supabase/migrations/08_reconcile.sql          <-- REQUIRED, run last
```

**08 is not optional.** Run 01–07 on top of `supabase-setup.sql` without it
and `is_active_officer()` ends up reading the wrong table — **every officer
is locked out of everything**. 08 also collapses two conflicting
`append_audit()` definitions that would otherwise make the audit hash chain
impossible to verify.

You will see errors while running 03 and 07 (`column "occurred_at" does not
exist`, `column "created_by" does not exist`). **That is expected** — those
are the collisions 08 exists to repair. Keep going.

### 1.4 Verify it worked

```sql
select * from public.verify_audit_chain();
```
Must return `ok = true`, `chain intact`.

```sql
select proname, pg_get_function_identity_arguments(oid)
  from pg_proc where proname = 'append_audit';
```
Must return **exactly one row**. Two means 08 did not run.

### 1.5 Create your first officer

Sign up through your frontend, then in the SQL editor:

```sql
update public.profiles
   set role = 'admin', status = 'active'
 where email = 'you@example.com';
```

Every new signup now defaults to `role='viewer'`, `status='pending'` —
least privilege. An admin activates each account. (Before 08, new signups
defaulted to `investigator`, which meant anyone who registered could read
case data.)

### 1.6 Enable Realtime (optional)

**Database → Replication** → enable for `transactions`, `alerts`,
`ml_predictions` if you want the dashboard to update live.

---

## Part 2 — `SERVICE_API_KEY`

### What it is

A shared secret for **machine-to-machine** calls — a cron job, a SAHYOG
integration, another service. It is an alternative to a Supabase JWT, sent
as `x-api-key` instead of `Authorization: Bearer`.

A human officer never uses it. It grants admin-level API access with no
individual identity attached, which is exactly why it **cannot approve a
dossier** — that needs a named person, and the code enforces it.

### It is optional

Leave it blank and the `x-api-key` path is simply disabled. Everything still
works through normal officer login. Only set it if something automated needs
to call your API.

### How to create one

```bash
openssl rand -hex 32
```

or:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output into `backend/.env`:

```
SERVICE_API_KEY=<the 64-character hex string>
```

**Must be at least 32 characters.** Anything shorter is treated as *not
configured* — a 5-character "key" looks configured while being trivially
guessable, which is worse than having none.

The comparison uses `hmac.compare_digest`, not `==`. A plain `==` returns
early on the first mismatched byte, so response timing leaks the key one
character at a time.

### Using it

```bash
curl -X POST http://localhost:8000/trace \
  -H "x-api-key: <your key>" \
  -H "Content-Type: application/json" \
  -d '{"targets":[{"chain":"polygon","address":"0x..."}]}'
```

---

## Part 3 — `ML_API_URL` and `ML_API_KEY`

### What they are

The address of the **machine-learning service** — a separate FastAPI process
running the `aiml/` package. `ML_API_URL` is where it lives; `ML_API_KEY` is
the bearer token the backend sends when calling it.

### They are optional, and this is deliberate

Leave `ML_API_URL` blank and `/trace` still scores every wallet — using the
in-gateway heuristic engine — and reports `scoringMode: "heuristic"`.

With the ML service reachable, the model refines those scores and the mode
becomes `"ml+heuristic"`.

An officer with rule-based scoring is far better served than an officer
looking at an error page, and the `scoringMode` field tells you honestly
which one you are looking at.

### Running the ML service

The ML layer runs as its own process on a different port:

```bash
cd aiml
pip install -r requirements.txt
python -m uvicorn serving.app:app --port 8001
```

Then in `backend/.env`:

```
ML_API_URL=http://localhost:8001
ML_API_KEY=<same secret both sides agree on — generate it like SERVICE_API_KEY>
```

### Training it — the order matters

The model learns from wallets you have actually traced and officers have
actually judged. So:

```bash
# 1. trace real addresses (populates ml_predictions)
curl -X POST localhost:8000/trace -H "Authorization: Bearer $JWT" \
  -d '{"targets":[{"chain":"polygon","address":"0x..."}]}'

# 2. officers record verdicts (populates ml_feedback)
curl -X POST localhost:8000/ml/feedback -H "Authorization: Bearer $JWT" \
  -d '{"address":"0x...","chain":"polygon","verdict":"confirmed_fraud"}'

# 3. train
cd aiml && python -m src.train_risk --source supabase
```

Run step 3 first and it will tell you there is not enough data and exit
without producing a model. **That is correct behaviour, not a failure.**

---

## Part 4 — Backend `.env` in full

```bash
ENVIRONMENT=development

SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon public key>
SUPABASE_SERVICE_ROLE_KEY=<service_role secret — backend only>

CORS_ORIGINS=http://localhost:5173

SERVICE_API_KEY=                    # optional; openssl rand -hex 32

BTC_API=https://blockstream.info/api
ETHERSCAN_API=https://api.etherscan.io/v2/api
ETHERSCAN_API_KEY=<one key covers Ethereum, Polygon and BSC>
TRON_API=https://api.trongrid.io
TRONGRID_API_KEY=<optional but strongly recommended>

ML_API_URL=                         # optional
ML_API_KEY=
```

Frontend `.env`:

```bash
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon public key>
```

Never put `SUPABASE_SERVICE_ROLE_KEY` in the frontend. Vite inlines every
`VITE_*` variable into the JavaScript bundle, where anyone can read it.

---

## Part 5 — Start everything

```bash
# terminal 1 — backend
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8000

# terminal 2 — ML (optional)
cd aiml && python -m uvicorn serving.app:app --port 8001

# terminal 3 — frontend
cd frontend && npm install && npm run dev
```

Check it is alive:

```bash
curl localhost:8000/health
```

`checks.bsc_configured: true` means your Etherscan key is loaded.
`checks.ml_configured: false` is fine — that just means heuristic scoring.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Every officer gets 403 | Migration 08 not run — `is_active_officer()` is reading the wrong table |
| `verify_audit_chain()` says mismatch | Two `append_audit` functions; run 08 |
| `/trace` returns 404 with `providerErrors` | Address has no activity on that chain. Try the others — the address you gave me was on Polygon, not Ethereum |
| BSC/Ethereum/Polygon traces fail | `ETHERSCAN_API_KEY` not set |
| Tron traces rate-limited | Set `TRONGRID_API_KEY` |
| `scoringMode: "heuristic"` | Normal when `ML_API_URL` is unset |
| Training says "not trained" | Not enough officer feedback yet. Working as designed |

---

## Sources

- [Supabase API keys and RLS](https://supabase.com/docs/guides/api/api-keys)
- [Etherscan V2 multichain API](https://docs.etherscan.io/etherscan-v2/readme.md)
- [TronGrid API](https://developers.tron.network/reference/trongrid-v1-api-overview)
