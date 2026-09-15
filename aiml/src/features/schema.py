"""
Canonical feature contract for Chakravyuh SETU.

This module is the single source of truth for what a wallet feature vector
contains.  Training and serving BOTH import from here, which is the only
reliable way to stop training/serving skew -- the failure mode where a model
scores 0.95 AUC offline and produces garbage in production because the
serving code built column 17 differently.

Every feature is documented with the fraud typology it helps separate, so an
investigating officer (or a judge) can be told what the model is looking at.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FeatureGroup = Literal["volume", "velocity", "topology", "temporal", "taint", "structuring"]


@dataclass(frozen=True)
class Feature:
    name: str
    group: FeatureGroup
    description: str
    # what this feature is diagnostic of -- used in the analyst-facing
    # explanation panel, not by the model
    signal: str


FEATURES: list[Feature] = [
    # ---------------- volume ----------------
    Feature("total_in_usd", "volume", "Lifetime inbound value in USD",
            "Scale of collection activity"),
    Feature("total_out_usd", "volume", "Lifetime outbound value in USD",
            "Scale of onward movement"),
    Feature("balance_usd", "volume", "Inbound minus outbound",
            "Wallets that retain nothing are pass-through layers"),
    Feature("avg_value_usd", "volume", "Mean transfer size",
            "Sextortion and task fraud sit at low mean values"),
    Feature("value_stddev_usd", "volume", "Std deviation of transfer size",
            "Automated collection has low variance"),
    Feature("max_value_usd", "volume", "Largest single transfer",
            "Cash-out events to an exchange"),
    Feature("in_out_ratio", "volume", "Inbound value / outbound value",
            "Near 1.0 indicates a layering hop, not a destination"),

    # ---------------- velocity ----------------
    Feature("tx_count", "velocity", "Total transactions",
            "Activity level"),
    Feature("tx_velocity", "velocity", "Transactions per active day",
            "Burner wallets spike then die"),
    Feature("active_days", "velocity", "Days between first and last activity",
            "Burner wallets have very short lifespans"),
    Feature("dormancy_days", "velocity", "Days since last activity",
            "Dormant-then-burst is a classic mule signature"),
    Feature("lifespan_ratio", "velocity", "Active days / days since first seen",
            "Separates short-lived burners from long-lived services"),

    # ---------------- topology ----------------
    Feature("fan_in", "topology", "Distinct sending counterparties",
            "High fan-in with low fan-out = victim collection wallet"),
    Feature("fan_out", "topology", "Distinct receiving counterparties",
            "High fan-out = distribution or mixer"),
    Feature("fan_ratio", "topology", "fan_in / (fan_out + 1)",
            "The single strongest collector-vs-distributor signal"),
    Feature("counterparty_entropy", "topology", "Shannon entropy of counterparties",
            "Exchanges have high entropy; funnels collapse toward zero"),
    Feature("unique_cp_ratio", "topology", "Distinct counterparties / tx count",
            "Address reuse -- exchanges reuse hot wallets heavily"),
    Feature("cluster_size", "topology", "Size of the co-spend cluster",
            "Exchange clusters run to thousands of addresses"),
    Feature("degree_centrality", "topology", "Normalised degree in the local graph",
            "Hub detection"),
    Feature("reciprocity", "topology", "Share of counterparties seen in both directions",
            "Services transact both ways; mules rarely do"),

    # ---------------- temporal ----------------
    Feature("night_activity_ratio", "temporal", "Share of activity 00:00-05:00 UTC",
            "Automation and offshore operation"),
    Feature("weekend_ratio", "temporal", "Share of activity at weekends",
            "Human-operated vs scripted"),
    Feature("inter_tx_burstiness", "temporal", "Std/mean of inter-transaction gaps",
            "Scripted collection is highly regular"),
    Feature("hour_entropy", "temporal", "Shannon entropy of activity hour",
            "Round-the-clock operation indicates a service"),
    Feature("first_seen_age_days", "temporal", "Age of the wallet",
            "Freshly created wallets receiving large sums are high risk"),

    # ---------------- taint / threat proximity ----------------
    Feature("sanction_hops", "taint", "Hops to nearest OFAC-sanctioned address (99 = none)",
            "Direct regulatory exposure"),
    Feature("mixer_hops", "taint", "Hops to nearest known mixer (99 = none)",
            "Deliberate obfuscation"),
    Feature("exchange_hops", "taint", "Hops to nearest attributed exchange (99 = none)",
            "THE key output for PS 26183 -- distance to the freezable endpoint"),
    Feature("darknet_hops", "taint", "Hops to nearest darknet-linked address (99 = none)",
            "Darknet market participation"),
    Feature("max_taint_share", "taint", "Largest taint fraction from any flagged source",
            "Proportion of holdings traceable to known crime"),
    Feature("tainted_inflow_ratio", "taint", "Share of inbound value carrying taint",
            "Distinguishes an unlucky recipient from a deliberate launderer"),

    # ---------------- structuring / laundering ----------------
    Feature("peel_chain_depth", "structuring", "Longest detected peel chain",
            "Layering depth"),
    Feature("round_amount_ratio", "structuring", "Share of round-number transfers",
            "Automated payouts and tumbler denominations"),
    Feature("structuring_score", "structuring", "Share of transfers just below reporting thresholds",
            "Deliberate threshold evasion"),
    Feature("uniform_output_score", "structuring", "1 - (std/mean) of outbound values",
            "Mixer denomination uniformity"),
    Feature("self_loop_ratio", "structuring", "Share of transfers within own cluster",
            "Internal shuffling to inflate hop count"),
    Feature("cross_chain_flag", "structuring", "Bridge interaction observed (0/1)",
            "Cross-chain flight -- explicitly named in PS 26183"),
]

FEATURE_NAMES: list[str] = [f.name for f in FEATURES]
N_FEATURES = len(FEATURE_NAMES)

# Sentinel used for "no path found" in every *_hops feature.  Kept explicit
# because imputing these with a mean is actively harmful: "no path to a
# sanctioned address" is a meaningful observation, not missing data.
NO_PATH = 99

GROUPS: dict[str, list[str]] = {}
for _f in FEATURES:
    GROUPS.setdefault(_f.group, []).append(_f.name)


def describe(name: str) -> Feature | None:
    """Look up a feature for the analyst-facing explanation panel."""
    return next((f for f in FEATURES if f.name == name), None)


def validate_frame(df) -> None:
    """Fail loudly on schema drift rather than silently scoring nonsense."""
    missing = set(FEATURE_NAMES) - set(df.columns)
    if missing:
        raise ValueError(
            f"feature matrix is missing {len(missing)} columns: {sorted(missing)}"
        )
    extra = [c for c in df.columns if c not in FEATURE_NAMES
             and c not in {"address", "chain", "wallet_id", "time_step", "label"}]
    if extra:
        raise ValueError(f"unexpected columns in feature matrix: {extra}")
