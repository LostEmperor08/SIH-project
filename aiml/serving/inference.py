"""
Inference engine — loaded once at FastAPI startup, reused for every request.

Design constraints this satisfies:
  * models load ONCE (a per-request joblib.load costs ~300ms and would
    dominate your /trace latency)
  * thread-safe: LightGBM predict and sklearn predict are read-only on a
    fitted estimator, so no lock is needed on the hot path
  * degrades: a missing artifact disables that one model, it does not take
    the API down. An officer with rule-based scoring and no ML is far
    better served than an officer with a 500.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.explain import Explainer, counterfactual, narrate
from src.features.extract import Edge, build_for_addresses
from src.features.schema import FEATURE_NAMES, NO_PATH
from src.labeling import weak_labels as wl
from src.models.classifiers import FusionWeights, fuse_risk
from src.models.registry import Registry

log = logging.getLogger("chakravyuh.ml")


# =====================================================================
@dataclass
class ModelBundle:
    illicit: Any = None
    vasp: Any = None
    typology: Any = None
    anomaly: Any = None
    gnn: Any = None
    manifests: dict = None
    explainer: Explainer | None = None

    @property
    def ready(self) -> bool:
        return self.illicit is not None

    def status(self) -> dict:
        return {
            "loaded": [k for k in ("illicit", "vasp", "typology", "anomaly", "gnn")
                       if getattr(self, k) is not None],
            "versions": {k: m.get("version") for k, m in (self.manifests or {}).items()},
            "trained_at": {k: m.get("created_at") for k, m in (self.manifests or {}).items()},
            "ready": self.ready,
        }


_BUNDLE = ModelBundle(manifests={})


def load_models(artifacts_dir: str | Path = "artifacts") -> ModelBundle:
    """Call once from the FastAPI lifespan/startup hook."""
    global _BUNDLE
    reg = Registry(artifacts_dir)
    bundle = ModelBundle(manifests={})

    for name in ("illicit", "vasp", "typology", "anomaly", "gnn"):
        if not reg.exists(name):
            log.warning("model '%s' not found in %s — that capability is disabled",
                        name, artifacts_dir)
            continue
        try:
            obj, man = reg.load(name)
            setattr(bundle, name, obj)
            bundle.manifests[name] = {"version": man.version,
                                      "created_at": man.created_at,
                                      "metrics": man.metrics,
                                      "label_source": man.label_source}
            log.info("loaded %s v%s", name, man.version)
        except Exception as e:
            log.error("failed to load %s: %s", name, e)

    if bundle.illicit is not None:
        bundle.explainer = Explainer(bundle.illicit, FEATURE_NAMES)

    _BUNDLE = bundle
    return bundle


def get_bundle() -> ModelBundle:
    return _BUNDLE


# =====================================================================
def _rule_score(row: pd.Series) -> tuple[float, list[dict]]:
    """
    Deterministic score from the label functions.

    Kept independent of the models on purpose: it is the component an
    officer can verify by hand, and the one that still works on day one
    before any model is trained.
    """
    fired = wl.explain_row(row, wl.ILLICIT_LFS)
    pos = sum(f["confidence"] for f in fired if f["verdict"] == 1)
    neg = sum(f["confidence"] for f in fired if f["verdict"] == 0)
    total = pos + neg
    score = 0.0 if total == 0 else 100.0 * pos / total
    return score, fired


def score_wallets(
    features: pd.DataFrame,
    *,
    bundle: ModelBundle | None = None,
    explain: bool = True,
) -> list[dict]:
    """Score a feature frame. `features` must carry an 'address' column."""
    b = bundle or get_bundle()
    t0 = time.perf_counter()
    X = features[FEATURE_NAMES]
    n = len(X)

    illicit_p = b.illicit.predict_proba(X) if b.illicit else np.zeros(n)
    anom = b.anomaly.anomaly_score(X) if b.anomaly else np.zeros(n)

    vasp_pred = b.vasp.predict(X) if b.vasp else None
    typ_top = b.typology.top_typologies(X) if b.typology and b.typology.heads else [[]] * n

    contribs = b.explainer.top_contributions(X) if (explain and b.explainer) else [[]] * n

    out = []
    for i in range(n):
        row = features.iloc[i]
        rule, fired = _rule_score(row)
        sanctioned = bool(row.get("sanction_hops", NO_PATH) == 0)

        risk = fuse_risk(
            rule_score=rule,
            illicit_proba=float(illicit_p[i]),
            anomaly_score=float(anom[i]),
            sanctioned=sanctioned,
            w=FusionWeights(),
        )

        rec = {
            "address": row.get("address"),
            **risk,
            "illicit_probability": round(float(illicit_p[i]), 4),
            "anomaly_score": round(float(anom[i]), 4),
            "rule_score": round(rule, 2),
            "rules_fired": fired,
            "typologies": typ_top[i],
            "explanation": contribs[i],
            # The PS asks specifically for the NEAREST VASP receiving direct
            # deposits — that is this field, and it is what a freeze request
            # is addressed to.
            "hops_to_exchange": (None if row.get("exchange_hops", NO_PATH) >= NO_PATH
                                 else int(row["exchange_hops"])),
            "hops_to_sanctioned": (None if row.get("sanction_hops", NO_PATH) >= NO_PATH
                                   else int(row["sanction_hops"])),
            "hops_to_mixer": (None if row.get("mixer_hops", NO_PATH) >= NO_PATH
                              else int(row["mixer_hops"])),
        }

        if vasp_pred is not None:
            rec["vasp_attribution"] = {
                "type": vasp_pred.iloc[i]["vasp_type"],
                "confidence": float(vasp_pred.iloc[i]["confidence"]),
                "runner_up": vasp_pred.iloc[i]["runner_up"],
                "abstained": bool(vasp_pred.iloc[i]["abstained"]),
            }

        if explain:
            rec["narrative"] = narrate(contribs[i], risk)
            rec["counterfactual"] = counterfactual(contribs[i], risk)

        rec["recommended_actions"] = _recommend(rec)
        out.append(rec)

    log.info("scored %d wallets in %.1f ms", n, (time.perf_counter() - t0) * 1000)
    return out


def _recommend(rec: dict) -> list[str]:
    """
    Automated investigative recommendations — an explicit PS 26183 deliverable.

    Deliberately phrased as next steps for an officer, not as conclusions.
    The system proposes; a human decides.
    """
    acts: list[str] = []
    band = rec["risk_band"]
    h_ex = rec.get("hops_to_exchange")
    vasp = (rec.get("vasp_attribution") or {}).get("type")

    if rec.get("hops_to_sanctioned") == 0:
        acts.append("ESCALATE IMMEDIATELY — address is on the OFAC SDN list. "
                    "Notify FIU-IND and freeze on sight.")
    if h_ex == 0:
        acts.append("Wallet deposits DIRECTLY to an exchange — issue a Section 91 BNSS "
                    "notice to that VASP for KYC and freeze the deposit account.")
    elif h_ex is not None and h_ex <= 2:
        acts.append(f"Exchange endpoint reachable in {h_ex} hops — trace the intermediate "
                    "wallets and prepare a VASP notice for the terminal address.")
    elif h_ex is None:
        acts.append("No exchange endpoint traced yet — extend tracing depth or wait for "
                    "further ingest before issuing a notice.")

    if rec.get("hops_to_mixer") is not None and rec["hops_to_mixer"] <= 1:
        acts.append("Mixer exposure detected — preserve pre-mixer transaction evidence now; "
                    "post-mixer attribution may be unrecoverable.")

    if vasp == "exchange":
        acts.append("Cluster attributed to an exchange — route the request through the "
                    "SAHYOG portal to the registered VASP compliance contact.")
    elif vasp == "bridge":
        acts.append("Bridge interaction — open a parallel trace on the destination chain.")

    for t in rec.get("typologies", []):
        if t["typology"] in ("ransomware", "sextortion"):
            acts.append(f"Pattern consistent with {t['typology']} "
                        f"({t['confidence']:.0%}) — check NCRP for linked victim complaints.")

    if band in ("critical", "high") and not acts:
        acts.append("High composite risk — assign for manual review and add to watchlist.")
    if band == "low":
        acts.append("Low risk — monitor only; no immediate action indicated.")

    return acts


# =====================================================================
def score_from_subgraph(
    edges_raw: list[dict],
    addresses: list[str],
    *,
    sanctioned: set[str] | None = None,
    mixers: set[str] | None = None,
    exchanges: set[str] | None = None,
    darknet: set[str] | None = None,
    bridges: set[str] | None = None,
    explain: bool = True,
) -> list[dict]:
    """
    The main serving path: a traced subgraph in, scored wallets out.

    Wire this straight to the output of your existing /trace endpoint — the
    same edges you already fetched from Blockstream/Blockscout, no second
    round trip to any provider.
    """
    edges = [
        Edge(e["from_address"], e["to_address"],
             float(e.get("value_usd", 0) or 0),
             float(e["ts"]) if isinstance(e.get("ts"), (int, float))
             else pd.Timestamp(e.get("block_time") or e.get("ts")).timestamp(),
             e.get("tx_hash", ""))
        for e in edges_raw
    ]
    feats = build_for_addresses(
        edges, addresses,
        sanctioned=sanctioned, mixers=mixers, exchanges=exchanges,
        darknet=darknet, bridges=bridges,
    )
    return score_wallets(feats, explain=explain)
