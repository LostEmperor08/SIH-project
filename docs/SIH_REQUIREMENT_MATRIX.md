# SIH 2026 Problem Statement 26183 — Requirement Traceability Matrix

> **Title**: Real-Time Identification of Fraud-Linked Cryptocurrency Exchanges from Victim-Reported Suspect Wallet Addresses through Automated Blockchain Analytics
> **Project**: Chakravyuh SETU

---

| Requirement ID | SIH Core Requirement | System Implementation | Verification Evidence | Demo Step | Status | Limitations / Notes |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| **REQ-01** | Victim-Reported Suspect Wallet Ingestion | `investigation_cases` DB table & `CaseWorkspaceService` (`app/services/cases.py`) | 252 backend unit tests (`test_case_workspace.py`) | Step 1–2 | **OPERATIONAL** | Validates ETH, Polygon, BSC, Tron, BTC address formats. |
| **REQ-02** | Automatic Multi-Hop Blockchain Tracing | Multi-chain provider pipeline with Etherscan V2, Blockstream, TronGrid (`app/providers/adapters.py`) | `test_trace.py` & `test_real_addresses.py` | Step 3–4 | **OPERATIONAL** | Rate-limit pacing protects provider APIs; fallback caching active. |
| **REQ-03** | Recursive Fund Attribution & Taint Propagation | Path-aware FIFO/pro-rata attribution engine (`app/services/fund_attribution.py`) | `test_fund_attribution.py` & `test_golden_investigation.py` | Step 5 | **OPERATIONAL** | Conserves value across splits/merges; decoupled from risk score. |
| **REQ-04** | Intermediary & Mule Wallet Detection | Multi-hop graph analysis with transaction velocity & modified Z-score (`app/services/risk.py`) | `test_risk_hardening.py` | Step 6 | **OPERATIONAL** | Identifies rapid forwarding and high-volume passthrough nodes. |
| **REQ-05** | Cross-Chain Bridge Correlation | Cross-chain bridge directory & transfer matcher (`app/services/bridge_correlation.py`) | `test_bridge_correlation.py` | Step 7–8 | **OPERATIONAL** | Correlates Hop, Synapse, Stargate, Hyphen, Portal bridges. |
| **REQ-06** | Known VASP / Crypto Exchange Identification | Exchange wallet directory, roles, deterministic confidence (`app/services/vasp_intelligence.py`) | `test_vasp_intelligence.py` | Step 9–10 | **OPERATIONAL** | Bounded confidence scoring; separates deposit, hot, cold roles. |
| **REQ-07** | Actionable Risk & Relevance Scoring | Dual-score engine (Risk Score vs Case Relevance Score) (`app/services/risk.py`) | `test_risk.py` | Step 11 | **OPERATIONAL** | Risk ∈ [0, 100], Case Relevance ∈ [0, 100] cleanly decoupled. |
| **REQ-08** | Real-Time Monitoring & Streaming Alerting | Polling event engine with cursor state recovery & deduplication (`app/services/monitoring.py`, `alert_engine.py`) | `test_monitoring.py` & `test_alert_deduplication.py` | Step 12 | **OPERATIONAL** | Restart-resilient cursor tracking; 32-char idempotency keys. |
| **REQ-09** | Investigator Case Workspace | 11-tab interactive UI dashboard (`frontend/src/components/CaseWorkspace.jsx`) | Production Vite build verification | Step 1–12 | **OPERATIONAL** | Case-scoped notes, tasks, timeline, and path-filtered money trail. |
| **REQ-10** | Evidence Provenance & Cryptographic Chain | Canonical JSON hashing, SHA-256 chain integrity, zip exporter (`app/services/evidence_provenance.py`) | `test_evidence_provenance.py` | Step 13 | **OPERATIONAL** | Validates intact vs. tampered records; exports `manifest.json`. |
| **REQ-11** | Server-Side Versioned Investigation Reports | Standardized versioned HTML/PDF templates with PDF SHA-256 hash verification (`app/services/reports.py`) | `test_report_generation.py` | Step 14–15 | **OPERATIONAL** | Cryptographically links report hash to database registry. |
| **REQ-12** | NCRP & SAHYOG Integration Layer | Official action adapters with simulation mode indicators (`app/services/integrations/ncrp.py`, `sahyog.py`) | `test_government_integrations.py` | Step 15 | **SIMULATION** | Operating in explicit `SIMULATION` mode unless live endpoints configured. |
