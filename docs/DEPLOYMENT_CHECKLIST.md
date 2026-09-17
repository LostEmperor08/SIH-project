# Chakravyuh SETU — Pre-Flight & Production Deployment Checklist

## Environment & Configuration
- [x] Python 3.10+ virtual environment created and active
- [x] Node.js 18+ and npm installed
- [x] `.env` file configured with required API keys (`ETHERSCAN_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`)
- [x] Environment variable `ENVIRONMENT` set to `production` or `development`

## Database & Schema Verification
- [x] All Supabase migrations (`01` through `14`) applied cleanly from zero
- [x] RLS policies and indexes verified for all 14 tables
- [x] Foreign key constraints and check constraints intact

## Backend Health & Readiness Probes
- [x] `GET /health` endpoint returns `ok: True`
- [x] `GET /ready` endpoint returns `status: "healthy"` and database status `"healthy"`
- [x] All 252 backend pytest unit and system integration tests passing (`pytest tests/`)

## Frontend Production Build
- [x] Production bundle builds with zero errors (`npx vite build`)
- [x] No raw API keys, JWTs, or service role keys leaked in compiled JS assets
- [x] Route-level lazy loading and graph component memoization verified

## Analytical Engine Verification
- [x] Recursive fund attribution engine conserves value across multi-hop paths
- [x] VASP Directory matches known exchange deposit/hot/cold wallets deterministically
- [x] Cross-chain bridge correlation extracts and matches transfer events across chains
- [x] Risk engine maintains strict decoupling between Risk Score and Case Relevance Score
- [x] Real-time monitoring cursor state recovers gracefully after service restart

## Security & Evidence Integrity
- [x] Evidence provenance chain verification returns `verdict: "INTACT"`
- [x] Exported evidence `.zip` contains valid `manifest.json` and SHA-256 hashes
- [x] PDF report verification endpoint validates uploaded report PDF hashes
- [x] NCRP & SAHYOG adapters clearly display `SIMULATION MODE` indicators in UI and API
