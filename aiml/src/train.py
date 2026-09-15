"""
Training orchestrator.

    python -m src.train --source supabase --chain btc
    python -m src.train --source elliptic
    python -m src.train --source synthetic --n 4000      # smoke test, no deps
    python -m src.train --source supabase --chain eth --with-gnn

Splits are TEMPORAL everywhere. This is the single most important choice in
the file: with a random split a wallet's own future transactions leak into
training and every metric you report is fiction. Elliptic's authors
demonstrated the same effect on this exact dataset.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .features.schema import FEATURE_NAMES
from .labeling import weak_labels as wl
from .models.classifiers import (
    AnomalyModel, IllicitModel, TypologyModel, VASPModel,
)
from .models.registry import Manifest, Registry


# =====================================================================
def load_config(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        p = Path(__file__).resolve().parent.parent / "config.yaml"
    return yaml.safe_load(p.read_text())


def temporal_split(df: pd.DataFrame, time_col: str,
                   test_frac: float = 0.2, val_frac: float = 0.1):
    """Oldest -> train, middle -> val, newest -> test."""
    order = df[time_col].rank(method="first", pct=True)
    tr = order <= (1 - test_frac - val_frac)
    va = (order > (1 - test_frac - val_frac)) & (order <= (1 - test_frac))
    te = order > (1 - test_frac)
    return tr.values, va.values, te.values


# =====================================================================
def make_synthetic(n: int = 4000, seed: int = 42) -> pd.DataFrame:
    """
    Synthetic wallets for smoke-testing the pipeline with no dependencies.

    NOT for reporting metrics — the fraud patterns here are the same ones
    the label functions look for, so accuracy is circular by construction.
    It exists so `train.py` can be proven to run end to end before you have
    live data or the Elliptic download.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        kind = rng.choice(
            ["retail", "exchange", "mixer", "collector", "mule",
             "ransomware", "task_fraud", "phishing"],
            p=[0.36, 0.09, 0.06, 0.13, 0.14, 0.07, 0.09, 0.06])

        base = {f: 0.0 for f in FEATURE_NAMES}
        base["sanction_hops"] = base["mixer_hops"] = 99.0
        base["exchange_hops"] = base["darknet_hops"] = 99.0

        if kind == "retail":
            base |= dict(
                tx_count=rng.integers(3, 40), fan_in=rng.integers(1, 8),
                fan_out=rng.integers(1, 8), avg_value_usd=rng.uniform(50, 900),
                active_days=rng.uniform(30, 500), cluster_size=rng.integers(1, 4),
                counterparty_entropy=rng.uniform(0.5, 2.0),
                exchange_hops=rng.integers(2, 5), mixer_hops=rng.integers(4, 9),
                sanction_hops=rng.integers(4, 9), darknet_hops=99)
        elif kind == "exchange":
            base |= dict(
                tx_count=rng.integers(2000, 20000), fan_in=rng.integers(500, 5000),
                fan_out=rng.integers(500, 5000), avg_value_usd=rng.uniform(200, 4000),
                active_days=rng.uniform(400, 1500), cluster_size=rng.integers(300, 4000),
                counterparty_entropy=rng.uniform(5.5, 9.0), unique_cp_ratio=rng.uniform(0.1, 0.45),
                hour_entropy=rng.uniform(2.6, 3.2), exchange_hops=0,
                mixer_hops=rng.integers(3, 8), sanction_hops=rng.integers(3, 8),
                reciprocity=rng.uniform(0.4, 0.8), darknet_hops=99)
        elif kind == "mixer":
            base |= dict(
                tx_count=rng.integers(500, 5000), fan_in=rng.integers(100, 900),
                fan_out=rng.integers(100, 900), avg_value_usd=rng.uniform(500, 5000),
                active_days=rng.uniform(100, 800), uniform_output_score=rng.uniform(0.78, 0.97),
                unique_cp_ratio=rng.uniform(0.86, 0.99), round_amount_ratio=rng.uniform(0.5, 0.9),
                mixer_hops=0, counterparty_entropy=rng.uniform(4, 7),
                peel_chain_depth=rng.integers(3, 9), sanction_hops=rng.integers(1, 4),
                darknet_hops=rng.integers(1, 4))
        elif kind == "collector":
            base |= dict(
                tx_count=rng.integers(40, 500), fan_in=rng.integers(25, 400),
                fan_out=rng.integers(1, 4), avg_value_usd=rng.uniform(150, 2500),
                active_days=rng.uniform(10, 90), exchange_hops=rng.integers(1, 3),
                mixer_hops=rng.integers(1, 4), sanction_hops=rng.integers(2, 6),
                counterparty_entropy=rng.uniform(2.5, 5.0),
                structuring_score=rng.uniform(0.0, 0.5), darknet_hops=99)
        elif kind == "mule":
            tin = rng.uniform(5000, 200000)
            base |= dict(
                tx_count=rng.integers(5, 60), fan_in=rng.integers(3, 30),
                fan_out=rng.integers(1, 6), total_in_usd=tin,
                total_out_usd=tin * rng.uniform(0.93, 1.0),
                active_days=rng.uniform(0.5, 40), dormancy_days=rng.uniform(0, 12),
                peel_chain_depth=rng.integers(2, 9), mixer_hops=rng.integers(1, 5),
                sanction_hops=rng.integers(1, 5), exchange_hops=rng.integers(1, 4),
                darknet_hops=rng.integers(2, 9))
        elif kind == "ransomware":
            base |= dict(
                tx_count=rng.integers(4, 30), fan_in=rng.integers(2, 14),
                fan_out=rng.integers(1, 3), avg_value_usd=rng.uniform(6000, 90000),
                active_days=rng.uniform(1, 45), dormancy_days=rng.uniform(0, 25),
                mixer_hops=rng.integers(0, 3), sanction_hops=rng.integers(0, 3),
                peel_chain_depth=rng.integers(1, 6), exchange_hops=rng.integers(2, 6),
                darknet_hops=rng.integers(1, 5))
        elif kind == "task_fraud":
            # many small victim payments at regular intervals, with small
            # refunds going back out — the "part-time job" scam shape
            base |= dict(
                tx_count=rng.integers(60, 900), fan_in=rng.integers(30, 400),
                fan_out=rng.integers(6, 38), avg_value_usd=rng.uniform(40, 380),
                active_days=rng.uniform(20, 180),
                inter_tx_burstiness=rng.uniform(0.15, 1.15),
                exchange_hops=rng.integers(1, 4), mixer_hops=rng.integers(2, 7),
                sanction_hops=rng.integers(2, 8), darknet_hops=99,
                counterparty_entropy=rng.uniform(3.0, 5.5))
        else:  # phishing / wallet drainer
            tin = rng.uniform(2000, 400000)
            base |= dict(
                tx_count=rng.integers(2, 9), fan_in=rng.integers(1, 5),
                fan_out=rng.integers(1, 4), avg_value_usd=tin / 8,
                total_in_usd=tin, total_out_usd=tin * rng.uniform(0.92, 1.0),
                active_days=rng.uniform(0.2, 4.5), dormancy_days=rng.uniform(0, 20),
                mixer_hops=rng.integers(1, 5), sanction_hops=rng.integers(2, 8),
                exchange_hops=rng.integers(1, 4), darknet_hops=99,
                max_value_usd=tin * rng.uniform(0.6, 0.95))

        base["total_in_usd"] = base.get("total_in_usd") or \
            base["avg_value_usd"] * max(base["fan_in"], 1)
        base["total_out_usd"] = base.get("total_out_usd") or base["total_in_usd"] * rng.uniform(0.6, 1.0)
        base["balance_usd"] = base["total_in_usd"] - base["total_out_usd"]
        base["max_value_usd"] = base.get("max_value_usd") or \
            base["avg_value_usd"] * rng.uniform(1.5, 12)
        base["value_stddev_usd"] = base["avg_value_usd"] * rng.uniform(0.1, 1.4)
        base["in_out_ratio"] = base["total_in_usd"] / (base["total_out_usd"] + 1)
        base["tx_velocity"] = base["tx_count"] / max(base["active_days"], 1)
        base["fan_ratio"] = base["fan_in"] / (base["fan_out"] + 1)
        base["unique_cp_ratio"] = base.get("unique_cp_ratio") or rng.uniform(0.3, 1.0)
        base["first_seen_age_days"] = base["active_days"] + rng.uniform(0, 400)
        base["lifespan_ratio"] = base["active_days"] / max(base["first_seen_age_days"], 1)
        base["degree_centrality"] = min(1.0, (base["fan_in"] + base["fan_out"]) / 8000)
        base["night_activity_ratio"] = rng.uniform(0, 0.6)
        base["weekend_ratio"] = rng.uniform(0.1, 0.4)
        base["inter_tx_burstiness"] = rng.uniform(0.2, 3.5)
        base["hour_entropy"] = base.get("hour_entropy") or rng.uniform(1.0, 3.1)
        base["reciprocity"] = base.get("reciprocity") or rng.uniform(0, 0.5)
        base["max_taint_share"] = 0.5 ** min(base["mixer_hops"], 8)
        base["tainted_inflow_ratio"] = rng.uniform(0, 1) if base["mixer_hops"] < 4 else rng.uniform(0, 0.15)
        base["self_loop_ratio"] = rng.uniform(0, 0.3)
        base["cross_chain_flag"] = float(rng.random() < 0.15)
        base["cluster_size"] = base.get("cluster_size") or rng.integers(1, 20)

        rows.append({"address": f"syn{i:07d}", "true_kind": kind,
                     "time_step": int(rng.integers(1, 50)), **base})

    return pd.DataFrame(rows)


# =====================================================================
def train_all(df: pd.DataFrame, cfg: dict, *, label_source: str,
              with_gnn: bool = False, edges=None) -> dict:
    reg = Registry(cfg["paths"]["artifacts_dir"])
    X_all = df[FEATURE_NAMES]
    time_col = "time_step" if "time_step" in df.columns else None
    if time_col is None:
        df = df.copy()
        df["time_step"] = np.arange(len(df))
        time_col = "time_step"

    tr, va, te = temporal_split(
        df, time_col,
        cfg["training"]["test_fraction"], cfg["training"]["val_fraction"])
    print(f"\n[split] train={tr.sum():,}  val={va.sum():,}  test={te.sum():,} (temporal)")

    results: dict = {"label_source": label_source,
                     "trained_at": datetime.now(timezone.utc).isoformat()}

    # ---------------- weak labels -----------------------------------
    print("\n[1/5] weak supervision")
    wres = wl.aggregate_binary(df)
    print(f"      coverage {wres.coverage:.1%} of wallets labelled")
    print(wres.lf_stats[["lf", "fires", "coverage"]].to_string(index=False))

    y_all = wres.labels
    w_all = wres.confidence
    labelled = (y_all != wl.ABSTAIN).values

    if labelled.sum() < 100:
        raise RuntimeError(
            f"only {labelled.sum()} wallets received a weak label. "
            "Ingest more data, or relax min_confidence in aggregate_binary()."
        )

    # ---------------- illicit ---------------------------------------
    print("\n[2/5] illicit classifier")
    m_tr, m_va, m_te = tr & labelled, va & labelled, te & labelled
    illicit = IllicitModel(**{k: v for k, v in cfg["illicit"].items()
                             if k in {"n_estimators", "learning_rate", "num_leaves",
                                      "min_child_samples", "subsample",
                                      "colsample_bytree", "reg_lambda"}})
    illicit.fit(X_all[m_tr], y_all[m_tr].values, X_all[m_va], y_all[m_va].values,
                sample_weight=w_all[m_tr].values)
    test_metrics = illicit.evaluate(X_all[m_te], y_all[m_te].values) \
        if m_te.sum() and len(np.unique(y_all[m_te])) > 1 else {}
    results["illicit"] = {"val": illicit.metrics, "test": test_metrics}
    if test_metrics:
        print(f"      test  AUC-PR={test_metrics['auc_pr']:.3f}  "
              f"ROC-AUC={test_metrics['roc_auc']:.3f}  F1={test_metrics['f1']:.3f}  "
              f"@thr={test_metrics['threshold']:.3f}")
    print("      top features:\n" +
          illicit.feature_importance(8).to_string(index=False))

    reg.save("illicit", illicit, Manifest(
        name="illicit", version="", created_at="", feature_names=FEATURE_NAMES,
        n_train=int(m_tr.sum()), n_val=int(m_va.sum()),
        metrics=results["illicit"], params=illicit.params,
        label_source=label_source))

    # ---------------- VASP ------------------------------------------
    print("\n[3/5] VASP / entity attribution")
    ent = wl.aggregate_entity(df)
    ent_labelled = (ent.labels != "unknown").values
    if ent_labelled.sum() >= 100 and ent.labels[ent_labelled].nunique() > 1:
        v_tr, v_va, v_te = tr & ent_labelled, va & ent_labelled, te & ent_labelled
        vasp = VASPModel(min_confidence=cfg["vasp"]["min_confidence"])
        vasp.fit(X_all[v_tr], ent.labels[v_tr].values,
                 X_all[v_va], ent.labels[v_va].values,
                 sample_weight=ent.confidence[v_tr].values)
        results["vasp"] = {
            "val": vasp.metrics,
            "test": vasp.evaluate(X_all[v_te], ent.labels[v_te].values) if v_te.sum() else {},
            "class_counts": ent.labels[ent_labelled].value_counts().to_dict(),
        }
        m = results["vasp"].get("test") or vasp.metrics
        if m:
            print(f"      accuracy(confident)={m.get('accuracy_when_confident', 0):.3f}  "
                  f"coverage={m.get('coverage', 0):.1%}")
        reg.save("vasp", vasp, Manifest(
            name="vasp", version="", created_at="", feature_names=FEATURE_NAMES,
            n_train=int(v_tr.sum()), n_val=int(v_va.sum()),
            metrics=results["vasp"], params=vasp.params, label_source=label_source))
    else:
        print("      skipped — not enough entity-labelled wallets yet")
        results["vasp"] = {"skipped": True}

    # ---------------- typology --------------------------------------
    print("\n[4/5] fraud typology")
    Y = wl.aggregate_typology(df, cfg["typology"]["labels"])
    print("      positives per typology:", Y.sum().to_dict())
    typ = TypologyModel(cfg["typology"]["labels"],
                        min_confidence=cfg["typology"]["min_confidence"])
    typ.fit(X_all[tr], Y[tr], X_all[va], Y[va])
    results["typology"] = {"heads_trained": list(typ.heads),
                           "metrics": typ.metrics,
                           "positives": Y.sum().to_dict()}
    if typ.heads:
        reg.save("typology", typ, Manifest(
            name="typology", version="", created_at="", feature_names=FEATURE_NAMES,
            n_train=int(tr.sum()), n_val=int(va.sum()),
            metrics=results["typology"], params=typ.params, label_source=label_source))

    # ---------------- anomaly ---------------------------------------
    print("\n[5/5] anomaly detector")
    anom = AnomalyModel(contamination=cfg["anomaly"]["contamination"])
    anom.fit(X_all[tr])
    scores = anom.anomaly_score(X_all[te]) if te.sum() else anom.anomaly_score(X_all)
    results["anomaly"] = {
        "mean_score": float(scores.mean()),
        "p95": float(np.percentile(scores, 95)),
        "flagged_frac": float((scores > 0.7).mean()),
    }
    print(f"      mean={scores.mean():.3f}  p95={np.percentile(scores, 95):.3f}  "
          f"flagged={results['anomaly']['flagged_frac']:.1%}")
    reg.save("anomaly", anom, Manifest(
        name="anomaly", version="", created_at="", feature_names=FEATURE_NAMES,
        n_train=int(tr.sum()), n_val=0, metrics=results["anomaly"],
        params=anom.params, label_source=label_source))

    # ---------------- optional GNN ----------------------------------
    if with_gnn and edges:
        print("\n[+] GraphSAGE")
        try:
            from .models.gnn import GNNWrapper, HAS_TORCH
            if not HAS_TORCH:
                raise ImportError("torch not installed")
            gnn = GNNWrapper(**{k: cfg["gnn"][k] for k in
                                ("hidden_dim", "num_layers", "dropout", "epochs", "lr")
                                if k in cfg["gnn"]})
            data, idx, _ = GNNWrapper.build_graph(
                df[["address"] + FEATURE_NAMES], edges)
            gnn.fit(data, y_all.replace(wl.ABSTAIN, 0).values, tr & labelled, va & labelled)
            results["gnn"] = gnn.metrics
            print(f"      val AUC-PR={gnn.metrics.get('val_auc_pr')}")
            reg.save("gnn", gnn, Manifest(
                name="gnn", version="", created_at="", feature_names=FEATURE_NAMES,
                n_train=int((tr & labelled).sum()), n_val=int((va & labelled).sum()),
                metrics=gnn.metrics, params=gnn.cfg, label_source=label_source))
        except ImportError as e:
            print(f"      skipped — {e}")
            results["gnn"] = {"skipped": str(e)}

    return results


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="Train the Chakravyuh SETU ML stack")
    ap.add_argument("--source", choices=["supabase", "elliptic", "synthetic"],
                    default="synthetic")
    ap.add_argument("--chain", default="btc")
    ap.add_argument("--n", type=int, default=4000, help="synthetic sample size")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--with-gnn", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    Path(cfg["paths"]["reports_dir"]).mkdir(parents=True, exist_ok=True)
    edges = None

    if args.source == "supabase":
        from .features.extract import build_from_supabase
        print(f"[data] pulling live graph for chain={args.chain}")
        df = build_from_supabase(args.chain, cfg["supabase"]["lookback_days"])
        label_source = f"weak_supervision:supabase:{args.chain}"

    elif args.source == "elliptic":
        # Elliptic has its own real labels, so it trains its own benchmark
        # model rather than going through weak supervision.
        from .labeling.elliptic import load_wallets
        X, y, ts = load_wallets(cfg["paths"]["elliptic_dir"])
        tr, va, te = temporal_split(pd.DataFrame({"t": ts}), "t",
                                    cfg["training"]["test_fraction"],
                                    cfg["training"]["val_fraction"])
        m = IllicitModel().fit(X[tr], y[tr].values, X[va], y[va].values)
        test = m.evaluate(X[te], y[te].values)
        print("\n=== Elliptic++ benchmark (temporal split) ===")
        print(f"AUC-PR  {test['auc_pr']:.4f}")
        print(f"ROC-AUC {test['roc_auc']:.4f}")
        print(f"F1      {test['f1']:.4f}  @threshold {test['threshold']:.3f}")
        print(f"base rate {test['base_rate']:.2%} — accuracy alone would be misleading")
        Registry(cfg["paths"]["artifacts_dir"]).save(
            "illicit_elliptic", m, Manifest(
                name="illicit_elliptic", version="", created_at="",
                feature_names=list(X.columns), n_train=int(tr.sum()),
                n_val=int(va.sum()), metrics={"test": test}, params=m.params,
                label_source="elliptic++_ground_truth",
                notes="Public benchmark; quote these numbers in the report."))
        out = Path(cfg["paths"]["reports_dir"]) / "elliptic_benchmark.json"
        out.write_text(json.dumps(test, indent=2))
        print(f"\nwrote {out}")
        return

    else:
        print(f"[data] generating {args.n} synthetic wallets (smoke test)")
        df = make_synthetic(args.n)
        label_source = "weak_supervision:synthetic"

    results = train_all(df, cfg, label_source=label_source,
                        with_gnn=args.with_gnn, edges=edges)

    out = Path(cfg["paths"]["reports_dir"]) / "training_report.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[done] report -> {out}")
    print(f"[done] models -> {cfg['paths']['artifacts_dir']}/")


if __name__ == "__main__":
    main()
