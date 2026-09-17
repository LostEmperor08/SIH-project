# Chakravyuh SETU (Chakravyuh-SETU)

### Real-Time Identification of Fraud-Linked Cryptocurrency Exchanges from Victim-Reported Suspect Wallet Addresses through Automated Blockchain Analytics

> **Smart India Hackathon (SIH) 2026 — Problem Statement 26183**

---

## 🛡️ Executive Summary

**Chakravyuh SETU** is an automated blockchain analytics, recursive fund attribution, and VASP (Virtual Asset Service Provider) intelligence platform engineered for law enforcement agencies and cyber-crime investigators.

When a victim reports a cryptocurrency fraud incident to the National Cyber Crime Reporting Portal (NCRP), fraudsters attempt to obscure money trails by rapidly forwarding funds across multi-hop suspect wallets, splitting/merging balances, crossing multi-chain bridges, and finally depositing into cryptocurrency exchange wallets. 

SETU solves this challenge by tracing blockchain fund flows in real time, recursively attributing victim funds, identifying target exchange endpoints with objective on-chain evidence, sealing investigation data in a cryptographic provenance ledger, and generating court-verifiable reports.

---

## 🎯 Primary Problem Addressed (SIH PS 26183)

| Challenge | Legacy Approach | Chakravyuh SETU Solution |
| :--- | :--- | :--- |
| **Multi-Hop Obfuscation** | Manual 1-hop manual lookup on block explorers. | Automated recursive multi-hop tracing across 5 major blockchains (ETH, Polygon, BSC, Tron, BTC). |
| **Fund Dilution & Splits** | Primitive percentage division creates false accounting. | Path-aware FIFO / Pro-Rata Recursive Fund Attribution Engine conserving value across splits/merges. |
| **Cross-Chain Bridges** | Money trail lost when funds cross chains. | Automated bridge event extraction & cross-chain transfer correlation matching source/destination events. |
| **Exchange Identification** | Unsubstantiated claims or manual subpoenas. | Deterministic VASP Directory & Cluster Intelligence matching deposit, hot, and cold wallet roles. |
| **Metric Confusion** | Exchange deposits mislabeled as "high risk". | Decoupled Risk Score ($0-100$) vs. Case Relevance Score ($0-100\%$) vs. VASP Confidence ($0-0.99$). |
| **Evidentiary Integrity** | Unsealed screenshots and spreadsheet logs. | Immutable Evidence Provenance Ledger with canonical JSON hashing & SHA-256 chain verification. |

---

## 🏗️ System Architecture & Workflow

```text
Victim Complaint / NCRP Report
            │
            ▼
    [Reported Suspect Wallet]
            │
            ▼
┌───────────────────────────────────────┐
│     Multi-Chain Provider Engine      │ (EVM, TronGrid, Esplora)
└───────────────────┬───────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│  Recursive Fund Attribution Engine    │ (FIFO / Pro-Rata Multi-Hop)
└───────────────────┬───────────────────┘
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
┌──────────────────┐ ┌──────────────────┐
│ Bridge Correlation│ │ VASP Intelligence│
└─────────┬────────┘ └─────────┬────────┘
          │                   │
          └─────────┬─────────┘
                    ▼
┌───────────────────────────────────────┐
│     Risk & Behavior Engine + ML      │ (Modified Z-score & Decoupled Metrics)
└───────────────────┬───────────────────┘
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
┌──────────────────┐ ┌──────────────────┐
│Realtime Monitor  │ │Investigator UI   │
└─────────┬────────┘ └─────────┬────────┘
          │                   │
          └─────────┬─────────┘
                    ▼
┌───────────────────────────────────────┐
│    Evidence Provenance & Reports     │ (Canonical JSON & Report Hash Verification)
└───────────────────────────────────────┘
```

---

## ⚙️ Core Engines & Technological Foundation

### 1. Recursive Fund Attribution Engine (`app/services/fund_attribution.py`)
- **Conservation of Value**: Attributed downstream funds are strictly bounded by the original victim loss pool.
- **Asset Isolation**: Transfers across different asset pools (ETH, USDT, TRX, BTC) are tracked separately.
- **Lineage Provenance**: Tracks exact path depth, quality level (`DIRECT`, `HIGH`, `MEDIUM`, `LOW`), and attribution method.

### 2. VASP Exchange Intelligence Engine (`app/services/vasp_intelligence.py`)
- **Role Classification**: Identifies exchange wallet roles (`DEPOSIT`, `HOT`, `COLD`).
- **Bounded Confidence**: Calculates deterministic VASP confidence ($0.0 - 0.99$) based on explicit on-chain evidence.

### 3. Cross-Chain Bridge Correlation Engine (`app/services/bridge_correlation.py`)
- **Bridge Support**: Automatically correlates transfers across Hop Protocol, Synapse, Stargate, Hyphen, Portal, and generic bridges.
- **Sequence & Fee Matching**: Matches source deposit logs with destination mint/release logs within fee tolerances.

### 4. Risk & Behavioral Intelligence Engine (`app/services/risk.py`)
- **Decoupled Analytical Metrics**: Separates Risk Score ($0-100$), Case Relevance ($0-100\%$), VASP Confidence ($0-0.99$), and ML Fraud Probability ($0-1.0$).
- **Statistical Anomaly Detection**: Uses modified Z-score analysis to flag rapid forwarding and extreme transaction velocity.

### 5. Real-Time Wallet Monitoring & Alert Engine (`app/services/monitoring.py`, `alert_engine.py`)
- **Cursor State Recovery**: Restarts safely resume from persistent block cursors without missing events or creating duplicate alerts.
- **Idempotency Protection**: Generates 32-character SHA-256 idempotency keys to deduplicate notification deliveries.

### 6. Evidence Provenance & Cryptographic Ledger (`app/services/evidence_provenance.py`)
- **Canonical Hashing**: `canonical_json()` ensures deterministic SHA-256 content hashing regardless of key ordering.
- **Evidence Sealing**: Chain verification validates hash continuity (`INTACT` / `TAMPERED`).
- **Zip Exporter**: Packages records, chain links, and `manifest.json` into exportable zip archives.

### 7. Versioned Investigation Reports (`app/services/reports.py`)
- **Server-Side Generation**: Produces versioned reports (`v1.0.0`) with HTML templates and PDF SHA-256 hash calculation.
- **Preservation Notices**: Generates Section 91 CrPC preservation notice documents pre-populated with target exchange metadata.

---

## 🚀 Quickstart & Installation

### Prerequisites
- Python 3.10+
- Node.js 18+ & npm
- Supabase account or local Postgres instance

### 1. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` in `backend/`:
```env
ENVIRONMENT=development
PORT=8000
SUPABASE_URL=https://your-supabase-url.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ETHERSCAN_API_KEY=your-etherscan-key
```

### 3. Run Backend Server & Verification
```bash
# Run FastAPI backend
python -m uvicorn main:app --reload --port 8000

# Run automated system verification script
python ../scripts/verify_system.py
```

### 4. Frontend Setup & Build
```bash
cd ../frontend
npm install
npm run dev

# Run production build check
npx vite build
```

---

## 🧪 Testing & Quality Assurance

### Run Comprehensive Backend Pytest Suite
All 252 backend unit and system integration tests run in under 7 seconds:
```bash
cd backend
python -m pytest tests/
```

Test coverage includes:
- `test_golden_investigation.py`: End-to-end golden investigation dataset scenario.
- `test_system_integration.py`: 12 comprehensive integration tests covering end-to-end flows, IDOR security, provider resilience, and NCRP/SAHYOG simulation.
- `test_data_consistency.py`: Numeric bounds, risk invariants, and multi-view data consistency checks.

---

## ⚠️ Explicit Environment Status & Limitations

1. **Government Portals (NCRP / SAHYOG)**: Outbound integration adapters operate in explicit **`SIMULATION`** mode unless live government credentials/endpoints are provided in environment configuration.
2. **Provider Rate Limits**: Third-party RPC provider limits (e.g. free Etherscan tier) are managed by internal rate-limit pacing adapters. Live queries fall back to cached block intelligence when rate limited.
3. **ML Scoring Model**: Operates with rule-based fallback when the standalone `aiml` Python service package is not mounted.

---

## 📜 License & Compliance

Developed for **Smart India Hackathon 2026** (Problem Statement 26183). Reserved for official law enforcement and cyber-crime investigation evaluation.
