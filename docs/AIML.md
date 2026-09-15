# Chakravyuh SETU — AI/ML Layer

AI/ML-assisted risk detection and automated pattern recognition for
**SIH PS 26183** (MHA / I4C): *Real-Time Identification of Fraud-Linked
Cryptocurrency Exchanges from Victim-Reported Suspect Wallet Addresses*.

Slots into your existing stack: React/Vite frontend → FastAPI backend →
Supabase. The ML layer mounts as a router on the FastAPI service you already run.

```
victim-reported address
        │
        ▼
   /trace  (your existing live provider gateway)
        │  edges: from, to, value_usd, ts
        ▼
   /ml/score  ──▶ feature extraction (37 features)
        │              │
        │              ├─ IllicitModel     is this fraud-linked?
        │              ├─ VASPModel        which exchange/service? ◀── the PS ask
        │              ├─ TypologyModel    which fraud type?
        │              └─ AnomalyModel     unlike anything seen before?
        │                      │
        │              score fusion (0–100, sanctions floor)
        │                      │
        │              SHAP → plain-English narrative
        ▼
  risk band + VASP + typologies + recommended actions + explanation
```

---

## Status: verified end to end

```
$ python -m src.train --source synthetic --n 6000
[split] train=4,200  val=600  test=1,200 (temporal)
[1/5] weak supervision       coverage 68.7%
[2/5] illicit classifier     AUC-PR=1.000  F1=0.998  @thr=0.528
[3/5] VASP attribution       accuracy(confident)=1.000  coverage=100%
[4/5] fraud typology         7/7 heads trained
[5/5] anomaly detector       flagged=5.5%

$ python -m tests.smoke_test
scored in 47.2 ms (9.4 ms/wallet)
12/12 checks PASSED
```

> **Read the metrics above as a pipeline check, not as accuracy.** They were
> produced on synthetic wallets generated from the same patterns the label
> functions look for — that is circular by construction, and a 1.000 AUC-PR
> is the *symptom*. What it proves is that the plumbing works end to end.
> Quote the Elliptic++ benchmark (below) in your report instead. Being
> straight about this in the viva is worth more than a big number.

---

## 1. Install and run

```bash
pip install -r requirements.txt

# smoke test — no data, no downloads, proves the pipeline
python -m src.train --source synthetic --n 6000
python -m tests.smoke_test

# the number you actually report
python -m src.train --source elliptic

# production: train on your own live Supabase graph
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
python -m src.train --source supabase --chain btc
```

Then run `sql/06_ml_tables.sql` in the Supabase SQL editor.

Optional GNN:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install torch-geometric
python -m src.train --source supabase --chain btc --with-gnn
```
Absent torch, the GNN stage is skipped with a note rather than crashing.

---

## 2. Wiring into your FastAPI backend

```python
# main.py
from serving.ml_router import router as ml_router
from serving.inference import load_models

app = FastAPI()

@app.on_event("startup")
async def _startup():
    load_models("artifacts")               # once, ~300ms
    app.state.verify_officer = verify_officer   # YOUR existing Supabase verifier
    app.state.supabase = supabase_client

app.include_router(ml_router)
```

`require_officer` in `ml_router.py` **fails closed** — if
`app.state.verify_officer` is unset every ML route returns 503 rather than
serving open. That matches the fail-closed posture in your report.

### Routes added

| Route | Purpose |
|---|---|
| `GET /ml/health` | Public liveness; exposes no model internals |
| `GET /ml/models` | Versions, training dates, metrics — the audit answer |
| `GET /ml/features` | The 37 features in plain language, for your UI |
| `POST /ml/score` | Full scoring from a traced subgraph |
| `POST /ml/triage` | Same, ~10× smaller payload for case-list screens |
| `POST /ml/score-features` | When features are already computed |
| `POST /ml/feedback` | Analyst ground truth — the learning loop |
| `POST /ml/reload` | Hot-swap new artifacts, admin only |

### Calling it from the frontend

```ts
const res = await fetch(`${API}/ml/score`, {
  method: "POST",
  headers: { Authorization: `Bearer ${session.access_token}`,
             "Content-Type": "application/json" },
  body: JSON.stringify({
    chain: "btc",
    addresses: [reportedWallet],
    edges: traceResult.edges,          // reuse what /trace already fetched
    sanctioned: traceResult.ofacHits,
    exchanges: traceResult.knownExchanges,
  }),
});
```

Response per wallet:

```jsonc
{
  "address": "SUSPECT_COLLECTOR",
  "risk_score": 75.86, "risk_band": "high",
  "components": { "rules": 100.0, "illicit_model": 55.67, "anomaly": 66.65 },
  "vasp_attribution": { "type": "merchant", "confidence": 1.0, "abstained": false },
  "typologies": [{ "typology": "investment_scam", "confidence": 0.91 }],
  "hops_to_exchange": 2, "hops_to_sanctioned": null, "hops_to_mixer": 2,
  "narrative": "Assessed at 75.86/100 (high risk). This wallet received $45,800 in total; is 2 hop(s) from a mixing service; has a collector profile (fan-in/out ratio 13.3)...",
  "explanation": [ { "feature": "fan_ratio", "value": 13.3, "impact": 0.42, "direction": "raises risk", "method": "shap" } ],
  "recommended_actions": [
    "Exchange endpoint reachable in 2 hops — trace the intermediate wallets and prepare a VASP notice for the terminal address."
  ]
}
```

---

## 3. How each PS 26183 requirement is met

| PS requirement | Implementation |
|---|---|
| Identify nearest exchange/VASP receiving direct deposits | `exchange_hops` feature + `VASPModel`; `hops_to_exchange == 0` is a direct deposit and triggers the Section 91 BNSS recommendation |
| Blockchain transaction graph analysis | 37 graph features; multi-source BFS proximity; peel-chain depth search |
| Clustering of exchange wallets | Behavioural fingerprints (fan ratio, uniformity, hot-wallet reuse) feeding `VASPModel` |
| Detection of intermediary laundering wallets | `mule` typology head + `in_out_ratio` + `peel_chain_depth` |
| Cross-chain fund movement | `cross_chain_flag`; chain-agnostic feature schema across btc/eth/polygon/tron/bsc |
| Risk categorisation of wallets | Fused 0–100 score → low / medium / high / critical |
| Automated alert generation | `risk_band` + `recommended_actions` |
| Automated investigative recommendations | `_recommend()` — BNSS notices, evidence preservation, SAHYOG routing |
| AI/ML-assisted risk detection | Four models + optional GraphSAGE |
| Automated pattern recognition for fraud typologies | 7 typology heads: investment scam, task fraud, sextortion, ransomware, phishing, darknet, mule |
| Integration with NCRP/SAHYOG | Recommendations name both; `ml_feedback.case_ref` links to complaint IDs |
| Standardised investigation reports | `narrative` + `explanation` drop into your existing dossier generator |

---

## 4. The five engineering decisions worth defending

**1. Temporal splits, never random.** A random split lets a wallet's own
future transactions into training. Elliptic's own authors showed this
inflates F1 substantially on this exact dataset, and a model validated that
way collapses the first time a new fraud campaign appears. Every split in
`train.py` is chronological.

**2. AUC-PR, not accuracy.** Elliptic++ wallets are ~5% illicit. Predicting
"all licit" scores 94.6% accuracy. Any accuracy figure quoted without a
class breakdown on this data is meaningless.

**3. Class weighting, not SMOTE.** Synthetic minority oversampling invents
wallets that never existed and wrecks probability calibration — fatal when
the output drives an asset-freezing decision. `scale_pos_weight` preserves
the calibration curve that risk banding depends on.

**4. Abstention is a first-class outcome.** `VASPModel` returns `unknown`
below 0.55 confidence rather than guessing. Telling an officer "this is
Binance" when it is not sends the freeze request to the wrong VASP and
burns the only chance to recover the funds.

**5. A sanctions floor the models cannot override.** A live OFAC hit pins
the score at ≥90 regardless of what any model thinks. A model may raise an
alarm; it is not permitted to talk one down. Verified by the smoke test.

---

## 5. The labelling problem, stated honestly

There is no public labelled dataset of Indian cyber-fraud wallets. Nobody
has one. So the layer uses three label sources, in descending order of trust:

| Source | Trust | Volume | Where |
|---|---|---|---|
| Analyst feedback | Highest — real investigations | Grows with use | `ml_feedback` table |
| Elliptic++ ground truth | High — published benchmark | 265k labelled wallets | `src/labeling/elliptic.py` |
| Weak supervision | Moderate — encodes FATF/FIU red flags | All live wallets | `src/labeling/weak_labels.py` |

**Weak supervision** runs 11 label functions for illicit/licit, 7 for entity
type and 7 for typology. Each votes or abstains; votes are aggregated by
confidence weight, not plain majority, so an OFAC hit (1.00) outweighs two
soft heuristics that disagree. Wallets where no function fires are left
unlabelled and excluded from training rather than guessed at. The resulting
confidence becomes the per-sample training weight.

This is not circular, because the label functions encode *published fraud
typologies*, not the model's own opinion — and every prediction traced to a
weak label is flagged as such in the API response, so an officer can tell
"OFAC says so" from "this resembles ransomware collection".

**The feedback loop is the real asset.** Every `/ml/feedback` call writes an
officer's verdict to Supabase. The next training run weights those above all
weak labels. Six months of deployment produces a labelled dataset of Indian
cyber-fraud wallets that does not currently exist anywhere — that is a
genuinely strong thing to say in the viva.

---

## 6. Getting real numbers for your report

```bash
git clone https://github.com/git-disl/EllipticPlusPlus
mkdir -p data/elliptic++
cp EllipticPlusPlus/"Actors Dataset"/*.csv data/elliptic++/
python -m src.train --source elliptic
# -> reports/elliptic_benchmark.json
```

This trains on **822,942 wallet addresses with real labels** (14,266
illicit, 251,088 licit, 557,588 unknown, 56 features, 49 time steps) and
prints AUC-PR, ROC-AUC, F1 and the base rate on a temporal split. Those are
the numbers to put in the report — they are reproducible, benchmarked
against published work, and defensible under questioning.

The loader also recomputes eight of *our* topology features from Elliptic's
`AddrAddr_edgelist.csv`. That matters: Elliptic's own 56 columns are
anonymised and do not map onto our named features, but the graph is real, so
degree, entropy and fan ratios computed from it mean the same thing there as
on your live Supabase graph. Those shared columns are what actually transfers.

---

## 7. Files

```
chakravyuh-aiml/
├── config.yaml                   all hyperparameters and thresholds
├── requirements.txt
├── src/
│   ├── features/
│   │   ├── schema.py             37 features — THE contract, shared train+serve
│   │   └── extract.py            Supabase/subgraph → feature matrix
│   ├── labeling/
│   │   ├── elliptic.py           Elliptic++ loader + topology recompute
│   │   └── weak_labels.py        25 label functions, confidence aggregation
│   ├── models/
│   │   ├── classifiers.py        the four models + score fusion
│   │   ├── gnn.py                optional GraphSAGE
│   │   └── registry.py           versioned artifacts with SHA-256 manifests
│   ├── explain.py                SHAP → officer-readable narrative
│   └── train.py                  training CLI
├── serving/
│   ├── inference.py              loaded-once engine, recommendations
│   └── ml_router.py              FastAPI router to mount
├── sql/06_ml_tables.sql          predictions, feedback, drift, RLS
└── tests/smoke_test.py           12-assertion end-to-end test
```

`src/features/schema.py` is the file to read first. It is the single source
of truth for what a feature vector contains, imported by both training and
serving — the only reliable defence against training/serving skew, where a
model scores 0.95 offline and produces garbage in production because the
serving code built column 17 differently.

---

## 8. Before you demo

- [ ] `python -m src.train --source elliptic` → real numbers for the report
- [ ] Retrain on live Supabase data once you have a few thousand wallets ingested
- [ ] Replace the `require_officer` placeholder with your actual verifier
- [ ] Run `sql/06_ml_tables.sql`
- [ ] Re-run `tests/smoke_test.py` after any feature change — it catches skew
- [ ] Seed 20–30 `ml_feedback` rows so `v_model_accuracy` has something to show

**Strongest live demo:** paste a victim-reported address, show the graph,
then show `/ml/score` returning `hops_to_exchange: 1`, the VASP attribution,
and the auto-generated Section 91 BNSS recommendation. That is the problem
statement answered end to end in one screen.

---

## Sources

- [Elliptic++ dataset (git-disl)](https://github.com/git-disl/EllipticPlusPlus) — 822,942 labelled wallet addresses
- [Demystifying Fraudulent Transactions and Illicit Nodes in the Bitcoin Network (KDD '23)](https://dl.acm.org/doi/pdf/10.1145/3580305.3599803) — the Elliptic++ paper
- [Elliptic Bitcoin dataset — PyG guide](https://kumo.ai/pyg/datasets/elliptic-bitcoin/)
- [Machine learning in classifying bitcoin addresses (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2405918823000259)
- [OFAC sanctioned digital currency addresses](https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses)
- [Entity-address dataset for 2010–2018 Bitcoin transactions](https://github.com/Maru92/EntityAddressBitcoin)
