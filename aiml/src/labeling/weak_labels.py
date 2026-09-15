"""
Weak supervision — programmatic labelling.

The honest problem with PS 26183: there is no public labelled dataset of
Indian cyber-fraud wallets. Nobody has one. So instead of pretending, we
generate labels programmatically from noisy, independently-fallible label
functions and aggregate them, in the Snorkel tradition. Each label function
(LF) votes ABSTAIN (-1) or a class; agreement across independent LFs is
treated as evidence.

Why this is defensible and not circular:

  * The LFs encode published fraud typologies and FATF/FIU red flags, not
    the model's own opinion.
  * LF outputs are aggregated with a confidence weight and the resulting
    labels are PROBABILISTIC — downstream training uses sample weights, so
    a wallet labelled by one weak LF does not count the same as one with a
    direct OFAC hit.
  * Every prediction traced back to a weak label is flagged as such in the
    API response, so an officer knows the difference between "OFAC says so"
    and "this pattern resembles ransomware collection".

Ground truth, when it arrives, comes from the analyst feedback loop
(ml_feedback table). Those labels supersede weak ones and are weighted
highest. That is how this system gets better after deployment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from ..features.schema import NO_PATH

ABSTAIN = -1


@dataclass
class LabelFunction:
    name: str
    fn: Callable[[pd.Series], int]
    confidence: float          # 0..1 — how much we trust this LF when it fires
    rationale: str             # shown to the officer
    typology: str | None = None

    def __call__(self, row: pd.Series) -> int:
        try:
            return self.fn(row)
        except Exception:
            return ABSTAIN


# =====================================================================
# ILLICIT / LICIT label functions  (binary: 1 illicit, 0 licit)
# =====================================================================
ILLICIT_LFS: list[LabelFunction] = [
    LabelFunction(
        "ofac_direct", lambda r: 1 if r.sanction_hops == 0 else ABSTAIN, 1.00,
        "Address appears on the OFAC SDN sanctioned digital-currency list",
    ),
    LabelFunction(
        "ofac_one_hop", lambda r: 1 if r.sanction_hops == 1 else ABSTAIN, 0.85,
        "Transacts directly with an OFAC-sanctioned address",
    ),
    LabelFunction(
        "mixer_direct", lambda r: 1 if r.mixer_hops == 0 else ABSTAIN, 0.80,
        "Direct interaction with a mixing/tumbling service",
    ),
    LabelFunction(
        "darknet_direct", lambda r: 1 if r.darknet_hops <= 1 else ABSTAIN, 0.80,
        "Direct or one-hop exposure to darknet market infrastructure",
    ),
    LabelFunction(
        "deep_peel", lambda r: 1 if r.peel_chain_depth >= 6 else ABSTAIN, 0.70,
        "Sits on a long peel chain — deliberate layering",
    ),
    LabelFunction(
        "structuring", lambda r: 1 if r.structuring_score > 0.35 else ABSTAIN, 0.65,
        "Transfers cluster just below reporting thresholds",
    ),
    LabelFunction(
        "burner_sweep",
        lambda r: 1 if (r.active_days < 3 and r.fan_in >= 15
                        and r.in_out_ratio > 0.9 and r.balance_usd < r.total_in_usd * 0.1)
        else ABSTAIN, 0.70,
        "Short-lived wallet that collected from many sources and swept out — burner pattern",
    ),
    LabelFunction(
        "funnel_to_mixer",
        lambda r: 1 if (r.fan_in >= 25 and r.fan_out <= 3 and r.mixer_hops <= 2)
        else ABSTAIN, 0.75,
        "Many-to-few collection feeding into a mixer",
    ),
    LabelFunction(
        "dormant_burst",
        lambda r: 1 if (r.first_seen_age_days > 180 and r.dormancy_days < 2
                        and r.tx_velocity > 8) else ABSTAIN, 0.55,
        "Long-dormant wallet suddenly highly active — reactivated mule",
    ),
    # --- negative (licit) evidence -----------------------------------
    LabelFunction(
        "established_service",
        lambda r: 0 if (r.cluster_size > 500 and r.counterparty_entropy > 5.0
                        and r.first_seen_age_days > 365 and r.sanction_hops >= 3
                        and r.mixer_hops >= 3) else ABSTAIN, 0.70,
        "Large, long-established, high-entropy cluster with no illicit proximity",
    ),
    LabelFunction(
        "low_risk_retail",
        lambda r: 0 if (r.tx_count < 30 and r.fan_in < 8 and r.fan_out < 8
                        and r.sanction_hops >= 4 and r.mixer_hops >= 4
                        and r.peel_chain_depth < 2) else ABSTAIN, 0.50,
        "Low-volume personal-scale wallet with no illicit proximity",
    ),
]


# =====================================================================
# VASP / ENTITY label functions
# =====================================================================
ENTITY_LFS: list[LabelFunction] = [
    LabelFunction(
        "exchange_hotwallet",
        lambda r: 1 if (r.cluster_size > 200 and r.fan_in > 300 and r.fan_out > 300
                        and r.unique_cp_ratio < 0.5 and r.hour_entropy > 2.5)
        else ABSTAIN, 0.80,
        "Very large bidirectional cluster with heavy address reuse and round-the-clock "
        "activity — exchange hot wallet",
        typology="exchange",
    ),
    LabelFunction(
        "mixer_uniform",
        lambda r: 1 if (r.uniform_output_score > 0.75 and r.fan_out > 80
                        and r.unique_cp_ratio > 0.85) else ABSTAIN, 0.80,
        "Near-uniform output denominations with high fan-out and no address reuse — mixer",
        typology="mixer",
    ),
    LabelFunction(
        "bridge_concentration",
        lambda r: 1 if (r.fan_in > 150 and r.fan_out <= 5 and r.cross_chain_flag > 0)
        else ABSTAIN, 0.75,
        "Many-to-few concentration with cross-chain activity — bridge contract",
        typology="bridge",
    ),
    LabelFunction(
        "gambling_micro",
        lambda r: 1 if (r.avg_value_usd < 120 and r.tx_count > 400
                        and r.reciprocity > 0.35) else ABSTAIN, 0.65,
        "High-frequency micro-value transfers with strong reciprocity — gambling service",
        typology="gambling",
    ),
    LabelFunction(
        "darknet_proximity",
        lambda r: 1 if r.darknet_hops <= 1 else ABSTAIN, 0.70,
        "Direct darknet market exposure", typology="darknet",
    ),
    LabelFunction(
        "merchant_steady",
        lambda r: 1 if (r.fan_in > 30 and r.fan_out < 15
                        and r.inter_tx_burstiness < 1.0
                        and r.night_activity_ratio < 0.2) else ABSTAIN, 0.55,
        "Steady inbound during business hours with low churn — merchant processor",
        typology="merchant",
    ),
    LabelFunction(
        "p2p_individual",
        lambda r: 1 if (r.cluster_size <= 5 and r.tx_count < 60 and r.fan_in < 12)
        else ABSTAIN, 0.55,
        "Small personal-scale cluster — individual wallet", typology="p2p",
    ),
]


# =====================================================================
# FRAUD TYPOLOGY label functions  (multi-label — a wallet can be several)
#
# Signatures drawn from the fraud types named in PS 26183.
# =====================================================================
TYPOLOGY_LFS: list[LabelFunction] = [
    LabelFunction(
        "investment_scam",
        lambda r: 1 if (r.fan_in >= 20 and r.fan_out <= 5
                        and r.active_days > 14
                        and r.avg_value_usd > 300
                        and r.exchange_hops <= 2) else ABSTAIN, 0.65,
        "Sustained collection from many distinct victims over weeks, then "
        "consolidation toward an exchange — investment/trading scam pattern",
        typology="investment_scam",
    ),
    LabelFunction(
        "task_fraud",
        lambda r: 1 if (r.fan_in >= 30 and r.avg_value_usd < 400
                        and r.inter_tx_burstiness < 1.2
                        and r.fan_out >= 5 and r.fan_out <= 40) else ABSTAIN, 0.60,
        "Very many small inbound transfers at regular intervals with small "
        "outbound refunds — task-based / part-time-job fraud",
        typology="task_fraud",
    ),
    LabelFunction(
        "sextortion",
        lambda r: 1 if (r.fan_in >= 10 and r.value_stddev_usd < r.avg_value_usd * 0.4
                        and r.avg_value_usd < 1500 and r.active_days < 30
                        and r.fan_out <= 3) else ABSTAIN, 0.60,
        "Many near-identical small payments over a short window with no "
        "onward movement until sweep — sextortion collection",
        typology="sextortion",
    ),
    LabelFunction(
        "ransomware",
        lambda r: 1 if (r.fan_in <= 15 and r.avg_value_usd > 5000
                        and r.mixer_hops <= 2 and r.dormancy_days < 30
                        and r.in_out_ratio > 0.85) else ABSTAIN, 0.70,
        "Few large inbound payments swept promptly toward a mixer — "
        "ransomware ransom collection",
        typology="ransomware",
    ),
    LabelFunction(
        "phishing",
        lambda r: 1 if (r.fan_in <= 5 and r.max_value_usd > r.avg_value_usd * 4
                        and r.active_days < 5 and r.in_out_ratio > 0.9)
        else ABSTAIN, 0.55,
        "Single large drain of a victim wallet moved on immediately — "
        "phishing / wallet-drainer",
        typology="phishing",
    ),
    LabelFunction(
        "darknet",
        lambda r: 1 if r.darknet_hops <= 2 else ABSTAIN, 0.70,
        "Within two hops of darknet market infrastructure",
        typology="darknet",
    ),
    LabelFunction(
        "mule",
        lambda r: 1 if (0.90 <= r.in_out_ratio <= 1.10 and r.dormancy_days < 14
                        and r.active_days < 60 and r.balance_usd < r.total_in_usd * 0.05)
        else ABSTAIN, 0.60,
        "Pass-through wallet retaining almost nothing — layering mule",
        typology="mule",
    ),
]


# =====================================================================
# Aggregation
# =====================================================================
@dataclass
class WeakLabelResult:
    labels: pd.Series           # the aggregated label
    confidence: pd.Series       # 0..1, used as a training sample weight
    coverage: float             # share of rows any LF fired on
    votes: pd.DataFrame         # per-LF votes, kept for the audit trail
    lf_stats: pd.DataFrame = field(default_factory=pd.DataFrame)


def apply_lfs(df: pd.DataFrame, lfs: list[LabelFunction]) -> pd.DataFrame:
    """Run every LF over every row. Returns an n_rows x n_lfs vote matrix."""
    return pd.DataFrame(
        {lf.name: df.apply(lf, axis=1) for lf in lfs},
        index=df.index,
    )


def aggregate_binary(
    df: pd.DataFrame,
    lfs: list[LabelFunction] = ILLICIT_LFS,
    *,
    min_confidence: float = 0.5,
) -> WeakLabelResult:
    """
    Confidence-weighted vote.

    Not a plain majority: an OFAC hit (confidence 1.00) must outweigh two
    soft heuristics that happen to disagree. Rows where no LF fires, or
    where the evidence is too weak, are left as -1 and excluded from
    training rather than guessed at.
    """
    votes = apply_lfs(df, lfs)
    conf = {lf.name: lf.confidence for lf in lfs}

    pos = sum(votes[n].eq(1) * c for n, c in conf.items())
    neg = sum(votes[n].eq(0) * c for n, c in conf.items())
    total = pos + neg

    labels = pd.Series(ABSTAIN, index=df.index, dtype=int)
    confidence = pd.Series(0.0, index=df.index, dtype=float)

    fired = total > 0
    margin = (pos - neg).abs() / total.where(total > 0, 1)
    decisive = fired & (margin >= (2 * min_confidence - 1)).fillna(False)

    labels[decisive & (pos > neg)] = 1
    labels[decisive & (neg >= pos)] = 0
    confidence[decisive] = margin[decisive].clip(0, 1)

    stats = pd.DataFrame([{
        "lf": lf.name,
        "fires": int(votes[lf.name].ne(ABSTAIN).sum()),
        "coverage": float(votes[lf.name].ne(ABSTAIN).mean()),
        "polarity": "illicit" if votes[lf.name].eq(1).any() else "licit",
        "confidence": lf.confidence,
        "rationale": lf.rationale,
    } for lf in lfs]).sort_values("coverage", ascending=False)

    return WeakLabelResult(
        labels=labels,
        confidence=confidence,
        coverage=float((labels != ABSTAIN).mean()),
        votes=votes,
        lf_stats=stats,
    )


def aggregate_entity(df: pd.DataFrame) -> WeakLabelResult:
    """Single-label entity/VASP class: highest-confidence LF that fires wins."""
    votes = apply_lfs(df, ENTITY_LFS)
    labels = pd.Series("unknown", index=df.index, dtype=object)
    confidence = pd.Series(0.0, index=df.index, dtype=float)

    for lf in sorted(ENTITY_LFS, key=lambda l: -l.confidence):
        hit = votes[lf.name].eq(1) & (confidence < lf.confidence)
        labels[hit] = lf.typology
        confidence[hit] = lf.confidence

    return WeakLabelResult(
        labels=labels, confidence=confidence,
        coverage=float((labels != "unknown").mean()), votes=votes,
    )


def aggregate_typology(df: pd.DataFrame, typologies: list[str]) -> pd.DataFrame:
    """
    Multi-label: returns an n_rows x n_typologies 0/1 frame.

    Deliberately NOT mutually exclusive — a ransomware wallet cashing out
    through a darknet-linked exchange is genuinely both, and forcing a
    single label there would destroy information the investigator needs.
    """
    votes = apply_lfs(df, TYPOLOGY_LFS)
    out = pd.DataFrame(0, index=df.index, columns=typologies, dtype=int)
    for lf in TYPOLOGY_LFS:
        if lf.typology in out.columns:
            out.loc[votes[lf.name].eq(1), lf.typology] = 1
    return out


def explain_row(row: pd.Series, lfs: list[LabelFunction]) -> list[dict]:
    """Which LFs fired on this wallet, and why — for the officer's dossier."""
    return [
        {"rule": lf.name, "verdict": int(v), "confidence": lf.confidence,
         "rationale": lf.rationale}
        for lf in lfs
        if (v := lf(row)) != ABSTAIN
    ]
