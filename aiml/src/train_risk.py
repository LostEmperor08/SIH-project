"""
Train the risk model on REAL traced data.

    python -m src.train_risk --source supabase       # production path
    python -m src.train_risk --source file rows.json # offline / CI

Replaces the synthetic-wallet training path. The old one generated wallets
from the same patterns the label functions detected, so its 1.000 AUC-PR was
circular by construction and could never be quoted honestly.

Where the data comes from
-------------------------
  ml_predictions   every wallet /trace has ever scored, with its heuristic
                   factors and stats — these become the FEATURES
  ml_feedback      officer verdicts on wallets they actually investigated —
                   these become the LABELS

So the training set grows every time an officer works a case. On day one
there is not enough to train, and the command says so plainly and exits
rather than producing a model from nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The feature contract lives with the code that computes it, in the backend.
# Importing it here (rather than redefining) is the whole point of the
# refactor: one definition, no drift.
_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if _BACKEND.exists() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

try:
    from app.services.risk import FEATURE_ORDER, FEATURE_VERSION, feature_vector
except ImportError as e:                               # pragma: no cover
    print(f"ERROR: cannot import the feature contract from {_BACKEND}\n  {e}\n"
          "The ML package must sit alongside backend/ so both share one\n"
          "definition of FEATURE_ORDER. Do not copy the list.", file=sys.stderr)
    raise SystemExit(2)

from .models.risk_model import AnomalyModel, RiskModel      # noqa: E402
from .models.registry import Manifest, Registry            # noqa: E402

VERDICT_TO_LABEL = {"confirmed_fraud": 1, "false_positive": 0}
# 'inconclusive' is deliberately excluded. Training on a maybe teaches the
# model to reproduce the analyst's uncertainty, which helps nobody.

# Weight by how much we trust the label's source.
WEIGHTS = {"confirmed_fraud": 1.0, "false_positive": 1.0}


# =====================================================================
def load_from_supabase() -> tuple[list[dict], list[int], list[float], dict]:
    import httpx

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.\n"
            "The service role key is server-side only — never put it in a "
            "browser build.")

    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    rest = f"{url.rstrip('/')}/rest/v1"

    with httpx.Client(timeout=60.0, headers=h) as c:
        fb = c.get(f"{rest}/ml_feedback",
                   params={"select": "chain,address,verdict,typology,created_at",
                           "order": "created_at.asc"})
        fb.raise_for_status()
        feedback = fb.json()

        pr = c.get(f"{rest}/ml_predictions",
                   params={"select": "chain,address,risk_score,explanation,"
                                     "hops_to_exchange,hops_to_sanctioned,"
                                     "hops_to_mixer,scored_at",
                           "order": "scored_at.desc"})
        pr.raise_for_status()
        preds = pr.json()

    # newest prediction per address wins
    by_addr: dict[str, dict] = {}
    for p in preds:
        k = f"{p['chain']}:{p['address']}"
        by_addr.setdefault(k, p)

    rows, labels, weights = [], [], []
    missing = 0
    for f in feedback:
        if f["verdict"] not in VERDICT_TO_LABEL:
            continue
        k = f"{f['chain']}:{f['address']}"
        p = by_addr.get(k)
        if p is None:
            missing += 1
            continue
        rows.append(_row_from_prediction(p))
        labels.append(VERDICT_TO_LABEL[f["verdict"]])
        weights.append(WEIGHTS.get(f["verdict"], 1.0))

    meta = {
        "feedback_rows": len(feedback),
        "predictions": len(by_addr),
        "matched": len(rows),
        "unmatched_feedback": missing,
    }
    # Unsupervised model trains on EVERY scored wallet, labelled or not.
    unlabelled = [_row_from_prediction(p) for p in by_addr.values()]
    meta["unlabelled_pool"] = len(unlabelled)
    return rows, labels, weights, {**meta, "_unlabelled": unlabelled}


def _row_from_prediction(p: dict) -> dict[str, float]:
    """
    Rebuild a feature vector from a stored ml_predictions row.

    The row carries the same shape score_graph() emits, so this goes through
    the SAME feature_vector() production uses.
    """
    score_like = {
        "risk_score": p.get("risk_score"),
        "factors": p.get("explanation") or [],
        "hops_to_exchange": p.get("hops_to_exchange"),
        "hops_to_sanctioned": p.get("hops_to_sanctioned"),
        "hops_to_mixer": p.get("hops_to_mixer"),
        "hops_to_darknet": None,
        "peel_chain_depth": 0,
        "stats": p.get("stats") or {},
    }
    return feature_vector(score_like)


def load_from_file(path: str) -> tuple[list[dict], list[int], list[float], dict]:
    """
    Offline path: a JSON array of {"features": {...}, "label": 0|1}.

    Used by CI and by anyone reproducing a result without database access.
    """
    data = json.loads(Path(path).read_text())
    rows = [d["features"] for d in data]
    labels = [int(d["label"]) for d in data]
    weights = [float(d.get("weight", 1.0)) for d in data]
    return rows, labels, weights, {"source_file": path, "_unlabelled": rows}


# =====================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Train the Chakravyuh risk model")
    ap.add_argument("--source", choices=["supabase", "file"], default="supabase")
    ap.add_argument("--file", help="JSON rows when --source file")
    ap.add_argument("--artifacts", default="artifacts")
    ap.add_argument("--model-weight", type=float, default=0.4,
                    help="weight given to the model when blending (default 0.4)")
    args = ap.parse_args()

    print(f"feature contract: v{FEATURE_VERSION}, {len(FEATURE_ORDER)} features")

    if args.source == "file":
        if not args.file:
            print("--file is required with --source file", file=sys.stderr)
            return 2
        rows, labels, weights, meta = load_from_file(args.file)
    else:
        rows, labels, weights, meta = load_from_supabase()

    unlabelled = meta.pop("_unlabelled", [])
    print("\ndata:")
    for k, v in meta.items():
        print(f"  {k:22s} {v}")

    if meta.get("unmatched_feedback"):
        print(f"\n  note: {meta['unmatched_feedback']} feedback row(s) had no "
              "matching prediction. Those wallets were labelled but never "
              "scored — re-run /trace on them so they can be used.")

    reg = Registry(args.artifacts)

    # ---- supervised -------------------------------------------------
    print("\n[1/2] supervised risk model")
    model = RiskModel(FEATURE_ORDER)
    rep = model.fit(rows, labels, weights)

    if not rep.trained:
        print(f"  NOT TRAINED — {rep.reason}")
        print("\n  This is the correct outcome, not a failure. The gateway")
        print("  heuristic keeps scoring every wallet, and /trace reports")
        print("  scoringMode:'heuristic'. Collect officer verdicts through")
        print("  POST /ml/feedback and re-run this.")
    else:
        m = rep.metrics
        print(f"  trained on {rep.n_train} wallets ({rep.n_positive} illicit)")
        if m:
            print(f"  AUC-PR  {m['auc_pr']:.3f}   ROC-AUC {m['roc_auc']:.3f}")
            print(f"  Brier   {m['brier']:.4f}  (calibration; lower is better)")
            print(f"  base rate {m['base_rate']:.1%} on {m['n_val']} held-out")
            print(f"  threshold {m['threshold']:.3f}")
        print("  top features:")
        for name, imp in rep.feature_importance[:8]:
            print(f"    {name:22s} {imp:.0f}")
        reg.save("risk_model", model, Manifest(
            name="risk_model", version="", created_at="",
            feature_names=FEATURE_ORDER, n_train=rep.n_train, n_val=rep.n_val,
            metrics=rep.metrics, params=model.params,
            label_source="ml_feedback (officer verdicts)",
            notes=f"feature contract v{FEATURE_VERSION}"))

    # ---- unsupervised -----------------------------------------------
    print("\n[2/2] anomaly model (needs no labels)")
    anom = AnomalyModel(FEATURE_ORDER)
    ares = anom.fit(unlabelled or rows)
    if ares.get("trained"):
        print(f"  trained on {ares['n']} wallets, mean score {ares['mean_score']:.3f}")
        reg.save("anomaly_model", anom, Manifest(
            name="anomaly_model", version="", created_at="",
            feature_names=FEATURE_ORDER, n_train=ares["n"], n_val=0,
            metrics=ares, params={"contamination": anom.contamination},
            label_source="unsupervised"))
    else:
        print(f"  NOT TRAINED — {ares['reason']}")

    out = Path(args.artifacts) / "training_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_version": FEATURE_VERSION,
        "data": meta,
        "supervised": {"trained": rep.trained, "reason": rep.reason,
                       "metrics": rep.metrics},
        "anomaly": ares,
    }, indent=2, default=str))
    print(f"\nreport -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
