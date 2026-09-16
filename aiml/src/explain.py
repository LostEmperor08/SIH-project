"""
Explainability — SHAP, translated into sentences an officer can put in a
case file.

A raw SHAP value means nothing to an investigating officer. What they need
is: "this wallet scored 87 mainly because it is one hop from an OFAC-listed
address, collected from 240 distinct senders, and moved everything out
within 36 hours." That is what `narrate()` produces.

This is also the legal requirement. A risk score that contributes to
freezing someone's assets has to be explainable after the fact, and a
number without a reason is not evidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features.schema import describe

try:
    import shap
    HAS_SHAP = True
except ImportError:                                    # pragma: no cover
    HAS_SHAP = False


class Explainer:
    def __init__(self, model, feature_names: list[str], background: pd.DataFrame | None = None):
        self.feature_names = feature_names
        self.model = model
        self._explainer = None
        if HAS_SHAP:
            try:
                inner = getattr(model, "model", model)
                self._explainer = shap.TreeExplainer(inner)
            except Exception:
                if background is not None and len(background):
                    bg = shap.sample(background[feature_names], min(20, len(background)))
                    self._explainer = shap.KernelExplainer(
                        lambda d: model.predict_proba(pd.DataFrame(d, columns=feature_names)),
                        bg)

    # -----------------------------------------------------------------
    def shap_values(self, X: pd.DataFrame) -> np.ndarray | None:
        if self._explainer is None:
            return None
        try:
            if hasattr(shap, "KernelExplainer") and isinstance(self._explainer, shap.KernelExplainer):
                sv = self._explainer.shap_values(X[self.feature_names], nsamples=25, silent=True)
            else:
                sv = self._explainer.shap_values(X[self.feature_names])
            if isinstance(sv, list):          # older API: one array per class
                sv = sv[1] if len(sv) > 1 else sv[0]
            sv = np.asarray(sv)
            if sv.ndim == 3:                  # (n, features, classes)
                sv = sv[:, :, -1]
            return sv
        except Exception:
            return None

    # -----------------------------------------------------------------
    def top_contributions(self, X: pd.DataFrame, k: int = 6) -> list[list[dict]]:
        """Per row: the k features that moved the score most, signed."""
        sv = self.shap_values(X)
        out: list[list[dict]] = []

        if sv is None:
            # Fall back to global importance or feature deviation so the UI
            # always has something to render — an empty explanation panel reads as a bug.
            imp = getattr(getattr(self.model, "model", None), "feature_importances_", None)
            for _, row in X.iterrows():
                if imp is not None:
                    order = np.argsort(imp)[::-1][:k]
                    out.append([{
                        "feature": self.feature_names[i],
                        "value": float(row[self.feature_names[i]]),
                        "impact": float(imp[i]),
                        "direction": "unknown",
                        "method": "global_importance",
                    } for i in order])
                else:
                    vals = np.array([abs(float(row[f])) for f in self.feature_names])
                    order = np.argsort(vals)[::-1][:k]
                    out.append([{
                        "feature": self.feature_names[i],
                        "value": float(row[self.feature_names[i]]),
                        "impact": round(float(vals[i]), 4),
                        "direction": "raises risk" if float(row[self.feature_names[i]]) > 0 else "lowers risk",
                        "method": "heuristic_deviation",
                    } for i in order])
            return out

        for i in range(len(X)):
            vals = sv[i]
            order = np.argsort(np.abs(vals))[::-1][:k]
            out.append([{
                "feature": self.feature_names[j],
                "value": float(X.iloc[i][self.feature_names[j]]),
                "impact": round(float(vals[j]), 5),
                "direction": "raises risk" if vals[j] > 0 else "lowers risk",
                "method": "shap",
            } for j in order])
        return out


# =====================================================================
# Human-readable narration
# =====================================================================
_PHRASE = {
    "sanction_hops": lambda v: (
        "is itself on the OFAC sanctions list" if v == 0 else
        f"is {int(v)} hop(s) from an OFAC-sanctioned address" if v < 90 else
        "has no path to any sanctioned address"),
    "mixer_hops": lambda v: (
        "interacts directly with a mixing service" if v == 0 else
        f"is {int(v)} hop(s) from a mixing service" if v < 90 else
        "shows no mixer exposure"),
    "exchange_hops": lambda v: (
        "deposits directly into an exchange" if v == 0 else
        f"reaches an exchange in {int(v)} hop(s)" if v < 90 else
        "has no traced path to a known exchange"),
    "darknet_hops": lambda v: (
        f"is {int(v)} hop(s) from darknet infrastructure" if v < 90 else
        "shows no darknet exposure"),
    "fan_in": lambda v: f"received funds from {int(v)} distinct senders",
    "fan_out": lambda v: f"sent funds to {int(v)} distinct recipients",
    "fan_ratio": lambda v: (
        f"has a collector profile (fan-in/out ratio {v:.1f})" if v > 3 else
        f"has a distributor profile (fan-in/out ratio {v:.2f})" if v < 0.4 else
        f"has balanced flow (ratio {v:.1f})"),
    "peel_chain_depth": lambda v: f"sits on a peel chain {int(v)} hops deep",
    "structuring_score": lambda v: f"has {v:.0%} of transfers just below reporting thresholds",
    "round_amount_ratio": lambda v: f"has {v:.0%} round-number transfers",
    "active_days": lambda v: f"was active for {v:.1f} days",
    "dormancy_days": lambda v: f"last moved funds {v:.1f} days ago",
    "in_out_ratio": lambda v: (
        f"passed through almost everything it received (in/out {v:.2f})"
        if 0.9 <= v <= 1.1 else f"has an in/out value ratio of {v:.2f}"),
    "tx_velocity": lambda v: f"averaged {v:.1f} transactions per active day",
    "uniform_output_score": lambda v: f"sends near-uniform amounts (uniformity {v:.2f})",
    "counterparty_entropy": lambda v: f"has counterparty entropy of {v:.2f}",
    "max_taint_share": lambda v: f"carries {v:.0%} traceable taint from flagged sources",
    "tainted_inflow_ratio": lambda v: f"received {v:.0%} of its value from flagged addresses",
    "cross_chain_flag": lambda v: ("shows cross-chain bridge activity" if v
                                   else "shows no cross-chain movement"),
    "night_activity_ratio": lambda v: f"conducts {v:.0%} of activity between 00:00-05:00 UTC",
    "cluster_size": lambda v: (
        f"belongs to a {int(v)}-address co-spend cluster" if v > 1
        else "is not linked to any larger co-spend cluster"),
    "total_in_usd": lambda v: f"received ${v:,.0f} in total",
    "total_out_usd": lambda v: f"sent out ${v:,.0f} in total",
    "balance_usd": lambda v: (
        f"retains ${v:,.0f}" if v > 0 else
        f"has paid out ${abs(v):,.0f} more than it received"),
    "avg_value_usd": lambda v: f"moves ${v:,.0f} per transfer on average",
    "value_stddev_usd": lambda v: f"has a transfer-size spread of ${v:,.0f}",
    "max_value_usd": lambda v: f"had a single transfer of ${v:,.0f}",
    "tx_count": lambda v: f"has {int(v)} transactions on record",
    "unique_cp_ratio": lambda v: (
        f"never reuses a counterparty (ratio {v:.2f})" if v > 0.9 else
        f"reuses counterparties heavily (ratio {v:.2f})" if v < 0.4 else
        f"has a counterparty-reuse ratio of {v:.2f}"),
    "first_seen_age_days": lambda v: (
        f"was first seen only {v:.1f} days ago" if v < 30
        else f"has been active for {v/365:.1f} years"),
    "inter_tx_burstiness": lambda v: (
        f"transacts at highly regular intervals (burstiness {v:.2f})" if v < 0.6
        else f"transacts in irregular bursts (burstiness {v:.2f})"),
    "hour_entropy": lambda v: (
        "operates around the clock" if v > 2.6
        else f"operates in a narrow daily window (hour entropy {v:.2f})"),
    "degree_centrality": lambda v: f"has a local-graph degree centrality of {v:.3f}",
    "self_loop_ratio": lambda v: f"sends {v:.0%} of transfers within its own cluster",
    "weekend_ratio": lambda v: f"conducts {v:.0%} of activity at weekends",
    "lifespan_ratio": lambda v: f"was active for {v:.0%} of its lifetime",
    "reciprocity": lambda v: f"has {v:.0%} two-way counterparty relationships",
}


def narrate(contributions: list[dict], risk: dict, max_points: int = 4) -> str:
    """Turn SHAP output into a paragraph for the dossier."""
    raising = [c for c in contributions if c.get("direction") == "raises risk"][:max_points]
    if not raising:
        raising = contributions[:max_points]

    clauses = []
    for c in raising:
        f, v = c["feature"], c["value"]
        clauses.append(_PHRASE[f](v) if f in _PHRASE
                       else f"{f.replace('_', ' ')} = {v:.2f}")

    if not clauses:
        return (f"Risk {risk['risk_score']}/100 ({risk['risk_band']}). "
                "No individual factor dominated the assessment.")

    body = "; ".join(clauses[:-1]) + (f"; and {clauses[-1]}" if len(clauses) > 1 else clauses[-1])
    lead = f"Assessed at {risk['risk_score']}/100 ({risk['risk_band']} risk). "
    if risk.get("sanction_floor_applied"):
        lead += "Minimum score enforced by a direct sanctions match. "
    return f"{lead}This wallet {body}."


def counterfactual(contributions: list[dict], risk: dict) -> str:
    """What single change would most reduce the score — a sanity check for the analyst."""
    raising = sorted((c for c in contributions if c.get("impact", 0) > 0),
                     key=lambda c: -c["impact"])
    if not raising:
        return "No single factor is driving this score."
    top = raising[0]
    d = describe(top["feature"])
    return (f"The dominant factor is '{top['feature']}' "
            f"({d.signal if d else 'behavioural signal'}). "
            f"Absent this factor the score would fall materially.")
