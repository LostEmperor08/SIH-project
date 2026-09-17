# Chakravyuh SETU — SIH 2026 Hackathon Demonstration Guide

> **Problem Statement 26183**: Real-Time Identification of Fraud-Linked Cryptocurrency Exchanges from Victim-Reported Suspect Wallet Addresses through Automated Blockchain Analytics

---

## 15-Step Presenter Sequence

### Step 1 — Open Case Workspace
- **Action**: Navigate to the **Case Workspace** tab. Select case `SIH/2026/00412`.
- **Narrative**: *"Welcome to Chakravyuh SETU. Here, law enforcement officers manage victim complaint cases in an isolated, secure workspace."*

### Step 2 — Review Reported Suspect Wallet
- **Action**: Click on the **Reported Wallet** banner showing `0x71c7656ec7ab88b098defb751b7401b5f6d8976f` (Ethereum).
- **Narrative**: *"The victim reported a loss of $10,000 USD transferred to this initial suspect wallet."*

### Step 3 — Trigger Automated Multi-Hop Trace
- **Action**: Click **Trace Money Trail**.
- **Narrative**: *"SETU automatically queries live blockchain nodes across Ethereum, Polygon, BSC, Tron, and Bitcoin, building a multi-hop graph in seconds."*

### Step 4 — Visualizing the Money Trail Graph
- **Action**: Switch to the **Money Trail** tab. Toggle graph filters (*Reported-Fund Flow*, *Exchange Endpoints*).
- **Narrative**: *"The money trail visualizes how funds split into 2 intermediate wallets before moving downstream."*

### Step 5 — Demonstrate Recursive Fund Attribution
- **Action**: Point out the **Attributed Value** ($7,000 USD / 70% share) on the Binance Hot Wallet node.
- **Narrative**: *"Unlike primitive 1-hop tools, SETU’s path-aware fund attribution engine tracks reported victim funds across splits and merges without double-counting."*

### Step 6 — Identify Intermediate Mule Wallets
- **Action**: Select intermediate node `0x9999...9901`. Show the transaction velocity and statistical value anomaly metrics.
- **Narrative**: *"SETU flags rapid forwarding intermediate wallets using modified Z-score statistical anomaly detection."*

### Step 7 — Cross-Chain Bridge Movement Detection
- **Action**: Open the **Cross-Chain** tab. Highlight the Hop Protocol transfer from Ethereum to Polygon.
- **Narrative**: *"Fraudsters attempt to wash funds by crossing chains. SETU automatically correlates cross-chain bridge transfers."*

### Step 8 — Show Destination Chain Activity
- **Action**: Inspect the Polygon destination transaction ($7,000 USDT).
- **Narrative**: *"SETU maintains attribution continuity across chain boundaries, following the money onto Polygon."*

### Step 9 — Exchange / VASP Identification
- **Action**: Switch to the **Exchanges** tab. Show the **Binance Hot Wallet** endpoint.
- **Narrative**: *"SETU matches the destination node against our VASP Directory with 95%+ deterministic confidence."*

### Step 10 — Explain VASP Evidentiary Grounds
- **Action**: Expand the VASP Evidence Drawer. Show exact on-chain match records and cluster intelligence.
- **Narrative**: *"Every exchange match is supported by objective on-chain evidence, identifying whether it is a deposit, hot, or cold wallet."*

### Step 11 — Explain Risk vs. Case Relevance Decoupled Model
- **Action**: Show the metric breakdown: **VASP Confidence** ($0.98$), **Case Relevance** ($100\%$), **Risk Score** ($25.0$).
- **Narrative**: *"We strictly decouple Risk from VASP Confidence. A known exchange deposit is highly relevant to the case, but does NOT mean the exchange itself is high-risk."*

### Step 12 — Demonstrate Real-Time Monitoring & Alerts
- **Action**: Open the **Alerts** tab. Show the streaming alert generated when suspect funds entered Binance.
- **Narrative**: *"SETU continuously monitors suspect wallets. When new movements occur, alerts are deduplicated and streamed to the investigator."*

### Step 13 — Evidence Provenance & Cryptographic Chain
- **Action**: Open the **Evidence** tab. Point out the `INTACT` chain status and click **Export Evidence Package (.zip)**.
- **Narrative**: *"All observed facts and derived analyses are sealed in an immutable cryptographic chain with canonical JSON SHA-256 hashing."*

### Step 14 — Generate Versioned Investigation Report
- **Action**: Click **Generate Investigation Report**. Preview the generated HTML/PDF document.
- **Narrative**: *"SETU generates versioned investigation reports (`v1.0.0`) complete with executive summaries, money trail tables, and legal limitation disclaimers."*

### Step 15 — PDF SHA-256 Verification & Government Actions
- **Action**: Highlight the report's PDF SHA-256 hash. Show the **NCRP / SAHYOG Official Action** cards labeled `SIMULATION MODE`.
- **Narrative**: *"Reports are cryptographically verifiable. Outbound portal integrations feature explicit simulation mode badges for complete transparency."*
