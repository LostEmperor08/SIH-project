"""
Risk scoring & VASP attribution engines — SIH 26183 specification.

Maintains THREE SEPARATE, independent concepts:
  1. Transaction Risk & Case Relevance (score_transaction)
  2. Wallet Risk (score_wallet / score_graph)
  3. VASP Attribution Confidence (calculate_vasp_attribution_confidence)

These are NEVER treated as interchangeable:
  * Wallet risk does NOT become transaction risk automatically.
  * Transaction risk does NOT become VASP attribution confidence.
  * VASP identification does NOT depend on wallet risk.
  * confidence is NEVER computed as risk_score / 100.
  * Direct sanctions match on wallets/transactions enforces a deterministic
    floor (minimum score 90.0 CRITICAL) with explicit override tracking.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..providers.base import NormEdge
from .fund_attribution import (
    compute_fund_attribution,
    AttributionResult,
    WalletAttribution,
    METHOD_UNAVAILABLE,
    QUALITY_UNAVAILABLE,
)

RISK_ENGINE_VERSION = "4.0.0"
SECONDS_PER_DAY = 86_400.0

# Evidence Source Types (Standardized for Batch 4 & 5)
SOURCE_OBSERVED = "OBSERVED_ON_CHAIN"
SOURCE_ENTITY = "KNOWN_ENTITY"
SOURCE_SANCTIONS = "SANCTIONS_SOURCE"
SOURCE_VASP = "VASP_DIRECTORY"
SOURCE_BRIDGE = "BRIDGE_DIRECTORY"
SOURCE_CASE = "CASE_RECORD"
SOURCE_MODEL = "MODEL_OUTPUT"
SOURCE_HEURISTIC = "HEURISTIC"

# Centralized Score Bands
TX_RISK_BANDS = [
    (80.0, "CRITICAL"),
    (60.0, "HIGH"),
    (40.0, "ELEVATED"),
    (20.0, "MODERATE"),
    (0.0, "LOW"),
]

WALLET_RISK_BANDS = [
    (80.0, "critical"),
    (60.0, "high"),
    (35.0, "medium"),
    (0.0, "low"),
]

BAND_CRITICAL = "critical"
BAND_HIGH = "high"


def tx_risk_band(score: float) -> str:
    for threshold, band in TX_RISK_BANDS:
        if score >= threshold:
            return band
    return "LOW"


def wallet_risk_band(score: float) -> str:
    for threshold, band in WALLET_RISK_BANDS:
        if score >= threshold:
            return band
    return "low"


@dataclass
class TransactionFactor:
    """One named contribution to a transaction's risk score."""
    code: str
    label: str
    raw_points: float
    confidence: float
    effective_points: float
    evidence: str
    source: str = "rule_engine"
    source_type: str = "heuristic"
    observations: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "raw_points": round(self.raw_points, 2),
            "confidence": round(self.confidence, 2),
            "effective_points": round(self.effective_points, 2),
            "evidence": self.evidence,
            "source": self.source,
            "source_type": self.source_type,
            "observations": self.observations,
        }


@dataclass
class Factor:
    """One named contribution to a wallet's risk score."""
    code: str
    label: str
    points: float
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class WalletStats:
    address: str
    chain: str
    in_usd: float = 0.0
    out_usd: float = 0.0
    tx_count: int = 0
    senders: set[str] = field(default_factory=set)
    receivers: set[str] = field(default_factory=set)
    values: list[float] = field(default_factory=list)
    times: list[float] = field(default_factory=list)
    assets: set[str] = field(default_factory=set)
    unvalued_count: int = 0

    @property
    def fan_in(self) -> int:
        return len(self.senders)

    @property
    def fan_out(self) -> int:
        return len(self.receivers)

    @property
    def balance_usd(self) -> float:
        return self.in_usd - self.out_usd

    @property
    def pass_through_ratio(self) -> float:
        return self.out_usd / self.in_usd if self.in_usd > 0 else 0.0

    @property
    def active_days(self) -> float:
        if len(self.times) < 2:
            return 0.0
        return (max(self.times) - min(self.times)) / SECONDS_PER_DAY

    @property
    def dormancy_days(self) -> float:
        if not self.times:
            return 0.0
        return (datetime.now(timezone.utc).timestamp() - max(self.times)) / SECONDS_PER_DAY


# =====================================================================
# TRANSACTION RISK & RELEVANCE ENGINE
# =====================================================================
def _epoch(iso_ts: str) -> float:
    try:
        return datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def _modified_z_score(val: float, vals: list[float]) -> float:
    """
    Modified Z-score using Median Absolute Deviation (MAD).
      modified_z = 0.6745 * (x - median) / MAD
    Resistant to heavy tails in cryptocurrency transfer distributions.
    """
    if len(vals) < 3:
        return 0.0
    med = _median(vals)
    devs = [abs(v - med) for v in vals]
    mad = _median(devs)
    if mad <= 1e-6:
        return 0.0
    return 0.6745 * (val - med) / mad


from .vasp_intelligence import (
    resolve_vasp_attribution,
    resolve_nearest_exchange,
    VaspAttribution,
)


def calculate_vasp_attribution_confidence(
    address: str,
    chain: str,
    *,
    wallets_intel: dict[str, dict] | None = None,
    explicit_vasp_name: str | None = None,
    explicit_entity_type: str | None = None,
    explicit_wallet_type: str | None = None,
) -> dict[str, Any] | None:
    """
    Independent VASP Attribution Confidence calculation.
    COMPLETELY DECOUPLED FROM RISK SCORES.
    Never uses risk_score / 100 or non-VASP high-risk fallbacks.
    """
    res = resolve_vasp_attribution(
        address, chain,
        wallets_intel=wallets_intel,
        explicit_vasp_name=explicit_vasp_name,
        explicit_entity_type=explicit_entity_type,
        explicit_wallet_type=explicit_wallet_type,
    )
    if not res.identified:
        return None
    return res.to_dict()


def score_transaction(
    edge: NormEdge,
    all_edges: list[NormEdge],
    targets: list[str],
    *,
    wallets_intel: dict[str, dict] | None = None,
    flags: dict[str, list[str]] | None = None,
    history_intel: dict[str, Any] | None = None,
    target_values: dict[str, float] | None = None,
    hop_map: dict[str, int] | None = None,
    attr_res: AttributionResult | dict | None = None,
) -> dict[str, Any]:
    """
    Transaction-Level Risk Engine & Relevance Scorer (SIH 26183 Batch 4).
    Bounded 100-point deterministic model with category budget caps & explicit evidence sources.
    """
    wallets_intel = wallets_intel or {}
    flags = flags or {}
    history_intel = history_intel or {}
    target_values = target_values or {}
    hop_map = hop_map or {}
    target_set = set(targets)

    frm, to = edge.from_address, edge.to_address
    chain = edge.chain
    val_usd = edge.value_usd

    factors: list[TransactionFactor] = []
    evidence_strings: list[str] = []
    flag_codes: list[str] = []

    def add_factor(
        code: str,
        label: str,
        raw_pts: float,
        conf: float,
        ev_text: str,
        *,
        source: str = "rule_engine",
        source_type: str = SOURCE_HEURISTIC,
        **obs
    ):
        eff_pts = raw_pts * conf
        if eff_pts > 0:
            factors.append(TransactionFactor(
                code=code, label=label, raw_points=round(raw_pts, 2),
                confidence=round(conf, 2), effective_points=round(eff_pts, 2),
                evidence=ev_text, source=source, source_type=source_type, observations=obs
            ))
            evidence_strings.append(ev_text)
            flag_codes.append(code)

    # 1. Fund-flow / Case Relevance (Category budget max: 20 pts)
    if isinstance(attr_res, AttributionResult):
        taint_share = attr_res.attribution_share
        attr_usd = attr_res.attributed_value_usd
        attr_method = attr_res.attribution_method
        attr_quality = attr_res.attribution_quality
        provenance_paths = attr_res.provenance_paths
    elif isinstance(attr_res, dict):
        taint_share = float(attr_res.get("attribution_share", 0.0))
        attr_usd = float(attr_res.get("attributed_value_usd", 0.0))
        attr_method = str(attr_res.get("attribution_method", METHOD_UNAVAILABLE))
        attr_quality = str(attr_res.get("attribution_quality", QUALITY_UNAVAILABLE))
        provenance_paths = attr_res.get("provenance_paths", [])
    else:
        total_target_val = sum(target_values.values()) if target_values else 0.0
        if total_target_val <= 0:
            target_txs = [e.value_usd for e in all_edges if e.from_address in target_set]
            total_target_val = sum(target_txs) if target_txs else val_usd

        taint_share = min(1.0, val_usd / max(total_target_val, 1.0)) if val_usd > 0 else 0.0
        attr_usd = val_usd * taint_share
        attr_method = "DIRECT_SOURCE" if (frm in target_set) else "PRO_RATA"
        attr_quality = "DIRECT" if (frm in target_set) else "MEDIUM"
        provenance_paths = []

    fund_attribution_share = taint_share

    if taint_share >= 0.80:
        add_factor("HIGH_FUND_ATTRIBUTION", "High case fund attribution", 20.0, 1.0,
                   f"Carries {taint_share:.1%} of reported case funds (${attr_usd:,.2f})",
                   source_type=SOURCE_CASE, taintShare=round(taint_share, 4), attributedUsd=round(attr_usd, 2))
    elif taint_share >= 0.50:
        add_factor("MODERATE_FUND_ATTRIBUTION", "Significant case fund attribution", 16.0, 1.0,
                   f"Carries {taint_share:.1%} of reported case funds (${attr_usd:,.2f})",
                   source_type=SOURCE_CASE, taintShare=round(taint_share, 4), attributedUsd=round(attr_usd, 2))
    elif taint_share >= 0.20:
        add_factor("PARTIAL_FUND_ATTRIBUTION", "Partial case fund attribution", 10.0, 0.9,
                   f"Carries {taint_share:.1%} of reported case funds (${attr_usd:,.2f})",
                   source_type=SOURCE_CASE, taintShare=round(taint_share, 4), attributedUsd=round(attr_usd, 2))
    elif taint_share >= 0.05:
        add_factor("LOW_FUND_ATTRIBUTION", "Low case fund attribution", 5.0, 0.8,
                   f"Carries {taint_share:.1%} of reported case funds (${attr_usd:,.2f})",
                   source_type=SOURCE_CASE, taintShare=round(taint_share, 4), attributedUsd=round(attr_usd, 2))
    elif taint_share > 0.0:
        add_factor("TRACE_PATH_MEMBER", "On case flow path", 1.0, 0.5,
                   "Minor flow on active case money path",
                   source_type=SOURCE_CASE, taintShare=round(taint_share, 4), attributedUsd=round(attr_usd, 2))

    # 2. Counterparty Intelligence (Category budget max: 15 pts)
    sanctions_set = set(flags.get("sanctioned", []))
    mixers_set = set(flags.get("mixers", []))
    darknet_set = set(flags.get("darknet", []))
    exchanges_set = set(flags.get("exchanges", []))
    illicit_set = set(flags.get("illicit", []))

    is_sanction_tx = frm in sanctions_set or to in sanctions_set
    if is_sanction_tx:
        add_factor("SANCTIONS_EXPOSURE", "Direct sanctions counterparty", 15.0, 1.0,
                   "Transaction directly involves an OFAC-sanctioned wallet address",
                   source_type=SOURCE_SANCTIONS, sanctionedAddress=to if to in sanctions_set else frm)
    elif to in mixers_set or frm in mixers_set:
        add_factor("MIXER_INTERACTION", "Mixer / tumbler interaction", 15.0, 0.9,
                   "Transaction interacts directly with a privacy mixer/tumbler",
                   source_type=SOURCE_ENTITY, mixerAddress=to if to in mixers_set else frm)
    elif to in darknet_set or frm in darknet_set:
        add_factor("DARKNET_ENDPOINT", "Darknet market exposure", 15.0, 0.9,
                   "Transaction interacts directly with darknet infrastructure",
                   source_type=SOURCE_ENTITY, darknetAddress=to if to in darknet_set else frm)
    elif to in illicit_set or frm in illicit_set:
        add_factor("ILLICIT_CLUSTER", "Known illicit cluster hit", 15.0, 0.9,
                   "Transaction counterparty belongs to a verified fraud cluster",
                   source_type=SOURCE_ENTITY, illicitAddress=to if to in illicit_set else frm)

    # 3. Behavioral Anomaly (Modified Z-score) (Category budget max: 15 pts)
    sender_vals = [e.value_usd for e in all_edges if e.from_address == frm]
    mod_z = _modified_z_score(val_usd, sender_vals)
    if mod_z >= 3.5:
        add_factor("EXTREME_VALUE_ANOMALY", "Extreme value anomaly", 15.0, 0.9,
                   f"Transfer amount (${val_usd:,.2f}) is an extreme statistical anomaly (Modified Z={mod_z:.1f})",
                   source_type=SOURCE_OBSERVED, modifiedZ=round(mod_z, 2))
    elif mod_z >= 2.5:
        add_factor("STRONG_VALUE_ANOMALY", "Strong value anomaly", 10.0, 0.8,
                   f"Transfer amount is a strong anomaly (Modified Z={mod_z:.1f})",
                   source_type=SOURCE_OBSERVED, modifiedZ=round(mod_z, 2))
    elif mod_z >= 1.5:
        add_factor("MODERATE_VALUE_ANOMALY", "Moderate value anomaly", 5.0, 0.7,
                   f"Transfer amount deviates from baseline (Modified Z={mod_z:.1f})",
                   source_type=SOURCE_OBSERVED, modifiedZ=round(mod_z, 2))

    # 4. Transaction Velocity / Rapid Forwarding (Category budget max: 10 pts)
    tx_time = _epoch(edge.block_time)
    incoming_times = [_epoch(e.block_time) for e in all_edges if e.to_address == frm and _epoch(e.block_time) <= tx_time]
    delay_sec = (tx_time - max(incoming_times)) if incoming_times else 999999.0

    in_val_sum = sum(e.value_usd for e in all_edges if e.to_address == frm)
    forward_ratio = (val_usd / in_val_sum) if in_val_sum > 0 else 0.0

    if 0 <= delay_sec < 60 and forward_ratio >= 0.85:
        add_factor("RAPID_PASS_THROUGH", "Rapid pass-through", 10.0, 0.95,
                   f"{forward_ratio:.1%} of received value forwarded {delay_sec:.0f} seconds after receipt",
                   source_type=SOURCE_OBSERVED, delaySeconds=round(delay_sec, 1), forwardedRatio=round(forward_ratio, 3))
    elif 0 <= delay_sec < 600 and forward_ratio >= 0.70:
        add_factor("FAST_FORWARDING", "Fast forwarding", 8.0, 0.90,
                   f"Forwarded {delay_sec / 60.0:.1f} minutes after receipt",
                   source_type=SOURCE_OBSERVED, delaySeconds=round(delay_sec, 1))
    elif 0 <= delay_sec < 3600:
        add_factor("ELEVATED_VELOCITY", "Elevated transaction velocity", 6.0, 0.80,
                   f"Forwarded within {delay_sec / 60.0:.0f} minutes",
                   source_type=SOURCE_OBSERVED, delaySeconds=round(delay_sec, 1))
    elif 0 <= delay_sec < 86400:
        add_factor("SAME_DAY_FORWARDING", "Same-day forwarding", 3.0, 0.70,
                   f"Forwarded within {delay_sec / 3600.0:.1f} hours",
                   source_type=SOURCE_OBSERVED, delaySeconds=round(delay_sec, 1))

    # 5. Graph Topology (Category budget max: 10 pts)
    frm_out_count = len({e.to_address for e in all_edges if e.from_address == frm})
    frm_in_count = len({e.from_address for e in all_edges if e.to_address == frm})
    to_out_count = len({e.to_address for e in all_edges if e.from_address == to})
    to_in_count = len({e.from_address for e in all_edges if e.to_address == to})

    if frm_in_count >= 15 and frm_out_count <= 3:
        add_factor("COLLECTION_FUNNEL", "Collection funnel flow", 10.0, 0.9,
                   f"Sourced from collection funnel ({frm_in_count} senders -> {frm_out_count} receivers)",
                   source_type=SOURCE_OBSERVED, fanIn=frm_in_count, fanOut=frm_out_count)
    elif frm_out_count >= 25 and frm_in_count <= 3:
        add_factor("DISTRIBUTION_PATTERN", "Distribution point flow", 8.0, 0.85,
                   f"Outbound flow from distribution hub ({frm_out_count} recipients)",
                   source_type=SOURCE_OBSERVED, fanOut=frm_out_count)

    # 6. Structuring Pattern (Category budget max: 10 pts)
    if 8000.0 <= val_usd <= 9999.0:
        near_struct_count = sum(1 for e in all_edges if 8000.0 <= e.value_usd <= 9999.0 and (e.from_address == frm or e.to_address == to))
        if near_struct_count >= 5:
            add_factor("STRUCTURING_HIGH", "Repeated threshold structuring", 10.0, 0.95,
                       f"Part of {near_struct_count} transfers clustered just below $10k reporting threshold",
                       source_type=SOURCE_OBSERVED, nearCount=near_struct_count)
        elif near_struct_count >= 3:
            add_factor("STRUCTURING_MODERATE", "Moderate threshold structuring", 7.0, 0.85,
                       f"Part of {near_struct_count} near-threshold transfers",
                       source_type=SOURCE_OBSERVED, nearCount=near_struct_count)
        else:
            add_factor("STRUCTURING_LOW", "Near-threshold transfer", 3.0, 0.70,
                       "Transfer amount sits just below $10k reporting threshold",
                       source_type=SOURCE_OBSERVED, nearCount=near_struct_count)

    # 7. Obfuscation / Cross-Chain / Bridge (Category budget max: 10 pts)
    bridges_set = set(flags.get("bridges", []))
    is_bridge_tx = frm in bridges_set or to in bridges_set

    if (frm in mixers_set or to in mixers_set) and delay_sec < 300:
        add_factor("MIXER_RAPID_FORWARDING", "Mixer rapid forwarding", 10.0, 0.95,
                   "Rapid movement immediately associated with a mixer endpoint",
                   source_type=SOURCE_BRIDGE)
    elif is_bridge_tx and delay_sec < 600:
        add_factor("BRIDGE_RAPID_FORWARDING", "Bridge rapid forwarding", 6.0, 0.85,
                   "Rapid cross-chain bridge transition",
                   source_type=SOURCE_BRIDGE)
    elif is_bridge_tx:
        add_factor("BRIDGE_CROSS_CHAIN", "Cross-chain bridge transition", 2.0, 0.80,
                   "Ordinary cross-chain bridge usage",
                   source_type=SOURCE_BRIDGE)

    # 8. Historical Intelligence (Category budget max: 5 pts)
    hist_hits = history_intel.get("case_hits", 0)
    if hist_hits > 0:
        add_factor("HISTORICAL_CASE_HIT", "Historical case intelligence hit", min(5.0, hist_hits * 2.5), 0.9,
                   f"Counterparty linked to {hist_hits} prior fraud investigation(s)",
                   source_type=SOURCE_CASE)

    # Calculate final effective score bounded at 100.0
    raw_total = sum(f.effective_points for f in factors)
    final_score = min(100.0, round(raw_total, 2))

    # Direct sanctions hard floor for transactions (minimum 90.0 CRITICAL)
    override_applied = False
    sanction_floor_reason = None
    sanction_source = None
    if is_sanction_tx:
        final_score = max(final_score, 90.0)
        override_applied = True
        sanction_floor_reason = "Direct verified sanctions match on transaction counterparty"
        sanction_source = "OFAC_SDN_LIST"

    band = tx_risk_band(final_score)
    avg_conf = (sum(f.confidence for f in factors) / len(factors)) if factors else 0.80

    # Calculate Relevance Score (0-100) independently (Relevance != Risk)
    rel_taint = taint_share * 40.0
    hop_dist = hop_map.get(to, hop_map.get(frm, 1))
    rel_hop = 35.0 if hop_dist == 1 else (25.0 if hop_dist == 2 else 15.0)
    rel_target = 20.0 if (frm in target_set or to in target_set) else 0.0
    rel_vasp = 15.0 if (to in exchanges_set or (wallets_intel.get(f"{chain}:{to}") or {}).get("entity_type") == "exchange") else 0.0

    relevance_score = min(100.0, round(rel_taint + rel_hop + rel_target + rel_vasp, 2))

    return {
        "tx_hash": edge.tx_hash,
        "from_address": frm,
        "to_address": to,
        "chain": chain,
        "asset": edge.asset,
        "amount": edge.value_native,
        "amount_usd": edge.value_usd,
        "timestamp": edge.block_time,
        "risk": {
            "score": final_score,
            "band": band,
            "confidence": round(avg_conf, 2),
            "sanction_floor_applied": override_applied,
            "sanction_floor_reason": sanction_floor_reason,
            "sanction_source": sanction_source,
            "factors": [f.to_dict() for f in sorted(factors, key=lambda x: -x.effective_points)],
        },
        "relevance": {
            "score": relevance_score,
            "taint_share": round(taint_share, 4),
            "fund_attribution_share": round(fund_attribution_share, 4),
            "attributed_value_usd": round(attr_usd, 2),
            "attribution_method": attr_method,
            "attribution_quality": attr_quality,
            "provenance_paths": provenance_paths,
            "hop": hop_dist,
        },
        "evidence": evidence_strings,
        "flags": flag_codes,
        "engine_version": RISK_ENGINE_VERSION,
    }


# =====================================================================
# WALLET-LEVEL RISK ENGINE
# =====================================================================
def build_stats(edges: list[NormEdge]) -> dict[str, WalletStats]:
    """Aggregate per-wallet statistics from the traced edge list."""
    stats: dict[str, WalletStats] = {}

    def get(addr: str, chain: str) -> WalletStats:
        k = f"{chain}:{addr}"
        if k not in stats:
            stats[k] = WalletStats(address=addr, chain=chain)
        return stats[k]

    for e in edges:
        ts = _epoch(e.block_time)
        unvalued = bool((e.raw or {}).get("unvalued"))

        s = get(e.from_address, e.chain)
        s.out_usd += e.value_usd
        s.receivers.add(e.to_address)
        s.tx_count += 1
        s.values.append(e.value_usd)
        s.times.append(ts)
        s.assets.add(e.asset)
        if unvalued:
            s.unvalued_count += 1

        d = get(e.to_address, e.chain)
        d.in_usd += e.value_usd
        d.senders.add(e.from_address)
        d.tx_count += 1
        d.values.append(e.value_usd)
        d.times.append(ts)
        d.assets.add(e.asset)
        if unvalued:
            d.unvalued_count += 1

    return stats


def _hops_map(edges: list[NormEdge], seeds: set[str], max_hops: int = 6) -> dict[str, int]:
    if not seeds:
        return {}
    adj: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        adj[e.from_address].add(e.to_address)
        adj[e.to_address].add(e.from_address)

    from collections import deque
    dist = {s: 0 for s in seeds if s in adj}
    q = deque(dist)
    while q:
        n = q.popleft()
        if dist[n] >= max_hops:
            continue
        for nb in adj[n]:
            if nb not in dist:
                dist[nb] = dist[n] + 1
                q.append(nb)
    return dist


def _detect_poisoning(
    counterparties: set[str],
    prefix_len: int = 6,
    suffix_len: int = 8,
    min_group: int = 3,
) -> dict[str, Any] | None:
    evm = [a for a in counterparties if a.startswith("0x") and len(a) == 42]
    if len(evm) < min_group:
        return None

    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for a in evm:
        groups[(a[:prefix_len].lower(), a[-suffix_len:].lower())].append(a)

    best_key, best = None, []
    for k, members in groups.items():
        if len(members) > len(best):
            best_key, best = k, members

    if best_key is None or len(best) < min_group:
        return None
    return {
        "count": len(best),
        "prefix": best_key[0],
        "suffix": best_key[1],
        "addresses": sorted(best)[:6],
    }


def _peel_depth(edges: list[NormEdge], start: str, max_depth: int = 12) -> int:
    out: dict[str, list[NormEdge]] = defaultdict(list)
    for e in edges:
        if e.value_usd > 0:
            out[e.from_address].append(e)

    best = 0
    stack: list[tuple[str, float, int, frozenset]] = [(start, math.inf, 0, frozenset([start]))]
    seen_states = 0
    while stack and seen_states < 5000:
        node, prev_val, depth, path = stack.pop()
        seen_states += 1
        best = max(best, depth)
        if depth >= max_depth:
            continue
        for e in sorted(out.get(node, []), key=lambda x: -x.value_usd)[:6]:
            if e.to_address in path:
                continue
            if prev_val == math.inf or (0.70 * prev_val <= e.value_usd <= 0.98 * prev_val):
                stack.append((e.to_address, e.value_usd, depth + 1, path | {e.to_address}))
    return best


def score_wallet(
    key: str,
    s: WalletStats,
    *,
    sanction_hops: int | None,
    mixer_hops: int | None,
    exchange_hops: int | None,
    darknet_hops: int | None,
    peel_depth: int,
    is_target: bool,
    tx_scores: list[dict[str, Any]] | None = None,
    wallets_intel: dict[str, dict] | None = None,
    wallet_attribution: WalletAttribution | dict | None = None,
) -> dict[str, Any]:
    """
    Score one wallet. Aggregates behavioral patterns AND transaction-level risk metrics.
    Enforces deterministic sanctions hard floor with explicit override tracking.
    """
    tx_scores = tx_scores or []
    wallets_intel = wallets_intel or {}
    intel = wallets_intel.get(key) or wallets_intel.get(s.address) or {}
    factors: list[Factor] = []

    def add(code, label, points, detail, **ev):
        if points > 0:
            factors.append(Factor(code, label, round(points, 2), detail, ev))

    # ---- sanctions ---------------------------------------------------
    if sanction_hops == 0:
        add("SANCTION_DIRECT", "Sanctioned address", 45,
            "Address appears on the OFAC SDN sanctioned digital-currency list",
            hops=0)
    elif sanction_hops == 1:
        add("SANCTION_1HOP", "One hop from sanctions", 25,
            "Transacts directly with an OFAC-sanctioned address", hops=1)
    elif sanction_hops == 2:
        add("SANCTION_2HOP", "Two hops from sanctions", 12,
            "Two hops from an OFAC-sanctioned address", hops=2)

    # ---- mixer -------------------------------------------------------
    if mixer_hops == 0:
        add("MIXER_DIRECT", "Direct mixer interaction", 30,
            "Transacts directly with a mixing/tumbling service", hops=0)
    elif mixer_hops == 1:
        add("MIXER_1HOP", "One hop from a mixer", 20,
            "One hop from a mixing service", hops=1)
    elif mixer_hops == 2:
        add("MIXER_2HOP", "Two hops from a mixer", 10,
            "Two hops from a mixing service", hops=2)

    # ---- darknet -----------------------------------------------------
    if darknet_hops is not None and darknet_hops <= 1:
        add("DARKNET_PROXIMITY", "Darknet exposure", 20,
            f"{darknet_hops} hop(s) from darknet market infrastructure",
            hops=darknet_hops)

    # ---- layering ----------------------------------------------------
    if peel_depth >= 3:
        add("PEEL_CHAIN", "Peel chain", min(15, peel_depth * 2.5),
            f"Sits on a peel chain {peel_depth} hops deep — deliberate layering",
            depth=peel_depth)

    # ---- structuring -------------------------------------------------
    if s.values:
        near = sum(1 for v in s.values if 8_000 <= v <= 9_999)
        ratio = near / len(s.values)
        if ratio > 0.15:
            add("STRUCTURING", "Threshold structuring", min(12, ratio * 40),
                f"{ratio:.0%} of transfers sit just below the $10k reporting threshold",
                ratio=round(ratio, 3))

    # ---- collection / distribution shape ------------------------------
    if s.fan_in >= 20 and s.fan_out <= 3:
        add("FUNNEL_ACCOUNT", "Collection funnel", 14,
            f"Received from {s.fan_in} distinct senders but pays out to only {s.fan_out}",
            fanIn=s.fan_in, fanOut=s.fan_out)
    elif s.fan_in >= 8 and s.fan_out <= 2:
        add("FUNNEL_WEAK", "Possible collection point", 7,
            f"Many-to-few flow ({s.fan_in} in, {s.fan_out} out)",
            fanIn=s.fan_in, fanOut=s.fan_out)

    if s.fan_out >= 30 and s.fan_in <= 3:
        add("DISTRIBUTOR", "Distribution point", 10,
            f"Pays out to {s.fan_out} distinct recipients from {s.fan_in} source(s)",
            fanIn=s.fan_in, fanOut=s.fan_out)

    # ---- pass-through (mule) -----------------------------------------
    if s.in_usd > 100 and 0.90 <= s.pass_through_ratio <= 1.02 and s.balance_usd < s.in_usd * 0.1:
        add("PASS_THROUGH", "Pass-through wallet", 12,
            f"Forwarded {s.pass_through_ratio:.0%} of everything received, retaining almost nothing — layering mule",
            ratio=round(s.pass_through_ratio, 3))

    # ---- burner ------------------------------------------------------
    if 0 < s.active_days < 3 and s.fan_in >= 5 and s.pass_through_ratio > 0.85:
        add("BURNER_SWEEP", "Burner wallet", 12,
            f"Collected from {s.fan_in} sources and swept out within {s.active_days:.1f} days",
            activeDays=round(s.active_days, 2))

    # ---- dormant burst -----------------------------------------------
    if s.active_days > 90 and s.dormancy_days < 3 and s.tx_count > 5:
        add("DORMANT_BURST", "Dormant-then-burst", 8,
            "Long-dormant wallet suddenly active again — reactivated mule",
            dormancyDays=round(s.dormancy_days, 1))

    # ---- address poisoning --------------------------------------------
    poison = _detect_poisoning(s.senders | s.receivers)
    if poison:
        add("ADDRESS_POISONING", "Address-poisoning cluster", 18,
            f"transacts with {poison['count']} counterparties sharing crafted pattern {poison['prefix']}…{poison['suffix']}",
            **poison)

    if s.values:
        dust = sum(1 for v in s.values if 0 < v < 0.01)
        if dust and poison:
            add("DUST_SEEDING", "Dust seeding", 6,
                f"{dust} near-zero transfer(s) alongside look-alike addresses",
                dustTransfers=dust)

    # ---- exchange proximity -------------------------------------------
    # Actionable endpoint, NOT intrinsic wickedness
    if exchange_hops == 0 and not is_target:
        add("EXCHANGE_ENDPOINT", "Exchange deposit endpoint", 5,
            "Funds deposit directly into an exchange — freezable endpoint",
            hops=0)

    # ---- Transaction Aggregates Contribution --------------------------
    tx_risks = [t.get("risk", {}).get("score", 0.0) for t in tx_scores if isinstance(t, dict)]
    high_tx_count = sum(1 for r in tx_risks if r >= 60.0)
    crit_tx_count = sum(1 for r in tx_risks if r >= 80.0)
    mean_tx_risk = (sum(tx_risks) / len(tx_risks)) if tx_risks else 0.0
    max_tx_risk = max(tx_risks) if tx_risks else 0.0

    if crit_tx_count > 0:
        add("CRITICAL_TRANSACTIONS_PRESENT", "Critical risk transactions present", min(15.0, crit_tx_count * 5.0),
            f"Wallet participated in {crit_tx_count} critical-risk transaction(s)",
            criticalTxCount=crit_tx_count)
    elif high_tx_count > 0:
        add("HIGH_RISK_TRANSACTIONS_PRESENT", "High risk transactions present", min(10.0, high_tx_count * 3.0),
            f"Wallet participated in {high_tx_count} high-risk transaction(s)",
            highTxCount=high_tx_count)

    total = min(100.0, sum(f.points for f in factors))

    # Direct sanctions hard floor with explicit override tracking
    floor_applied = False
    floor_reason = None
    if sanction_hops == 0:
        total = max(total, 90.0)
        floor_applied = True
        floor_reason = "Direct verified sanctions match on wallet address"

    band = wallet_risk_band(total)

    # Calculate Independent VASP Attribution Confidence
    vasp_attr = calculate_vasp_attribution_confidence(
        s.address, s.chain, wallets_intel=wallets_intel,
        explicit_vasp_name=intel.get("vasp_name"),
        explicit_entity_type=intel.get("entity_type")
    )

    if isinstance(wallet_attribution, WalletAttribution):
        w_attr_dict = wallet_attribution.to_dict()
    elif isinstance(wallet_attribution, dict):
        w_attr_dict = wallet_attribution
    else:
        w_attr_dict = {
            "address": s.address,
            "chain": s.chain,
            "attributed_inbound_usd": round(s.in_usd, 2) if is_target else 0.0,
            "attributed_outbound_usd": round(s.out_usd, 2) if is_target else 0.0,
            "total_inbound_usd": round(s.in_usd, 2),
            "total_outbound_usd": round(s.out_usd, 2),
            "attribution_share": 1.0 if is_target else 0.0,
            "attribution_quality": "DIRECT" if is_target else "UNAVAILABLE",
            "source_paths": [s.address] if is_target else [],
            "participating_sources": [s.address] if is_target else [],
        }

    # Construct structured alert events for Batch 5 handoff
    alert_events: list[dict[str, Any]] = []
    if floor_applied or sanction_hops == 0:
        alert_events.append({
            "event_type": "SANCTIONS_MATCH",
            "severity": "CRITICAL",
            "detail": "Direct sanctions match verified on wallet address",
            "address": s.address,
        })
    if crit_tx_count > 0 or total >= 80.0:
        alert_events.append({
            "event_type": "CRITICAL_RISK_THRESHOLD",
            "severity": "CRITICAL",
            "detail": f"Wallet risk score reached {total:.1f} (CRITICAL)",
            "address": s.address,
        })
    if "PASS_THROUGH" in {f.code for f in factors} or "BURNER_SWEEP" in {f.code for f in factors}:
        alert_events.append({
            "event_type": "RAPID_FORWARDING_MULE",
            "severity": "HIGH",
            "detail": "High-velocity pass-through mule pattern observed",
            "address": s.address,
        })
    if exchange_hops == 0 and not is_target:
        alert_events.append({
            "event_type": "KNOWN_EXCHANGE_REACHED",
            "severity": "HIGH",
            "detail": f"Funds deposit directly into exchange ({vasp_attr.get('name') if vasp_attr else 'Exchange'})",
            "address": s.address,
        })

    return {
        "address": s.address,
        "chain": s.chain,
        "risk_score": round(total, 2),
        "risk_band": band,
        "sanction_floor_applied": floor_applied,
        "sanction_floor_reason": floor_reason,
        "sanction_source": "OFAC_SDN_LIST" if floor_applied else None,
        "factors": [
            {"code": f.code, "label": f.label, "points": f.points,
             "detail": f.detail, "evidence": f.evidence}
            for f in sorted(factors, key=lambda x: -x.points)
        ],
        "vasp_attribution": vasp_attr,
        "fund_attribution": w_attr_dict,
        "transaction_aggregates": {
            "mean_transaction_risk": round(mean_tx_risk, 2),
            "max_transaction_risk": round(max_tx_risk, 2),
            "high_risk_tx_count": high_tx_count,
            "critical_tx_count": crit_tx_count,
            "total_scored_txs": len(tx_risks),
        },
        "hops_to_sanctioned": sanction_hops,
        "hops_to_mixer": mixer_hops,
        "hops_to_exchange": exchange_hops,
        "hops_to_darknet": darknet_hops,
        "peel_chain_depth": peel_depth,
        "stats": {
            "inUsd": round(s.in_usd, 2), "outUsd": round(s.out_usd, 2),
            "balanceUsd": round(s.balance_usd, 2),
            "txCount": s.tx_count, "fanIn": s.fan_in, "fanOut": s.fan_out,
            "activeDays": round(s.active_days, 2),
            "dormancyDays": round(s.dormancy_days, 2),
            "assets": sorted(s.assets),
            "unvaluedTransfers": s.unvalued_count,
        },
        "narrative": _narrate(s, factors, total, band),
        "recommended_actions": _recommend(
            band, sanction_hops, mixer_hops, exchange_hops, factors),
        "structured_alert_events": alert_events,
        "engine_version": RISK_ENGINE_VERSION,
    }


def _narrate(s: WalletStats, factors: list[Factor], total: float, band: str) -> str:
    if not factors:
        return (f"Assessed at {total:.0f}/100 ({band} risk). No risk factor "
                f"fired: {s.tx_count} transfers, {s.fan_in} senders, "
                f"{s.fan_out} recipients, no proximity to flagged infrastructure.")
    top = sorted(factors, key=lambda f: -f.points)[:4]
    clauses = [f.detail[0].lower() + f.detail[1:] for f in top]
    body = ("; ".join(clauses[:-1]) + f"; and {clauses[-1]}") if len(clauses) > 1 else clauses[0]
    lead = f"Assessed at {total:.0f}/100 ({band} risk). "
    if any(f.code == "SANCTION_DIRECT" for f in factors):
        lead += "Minimum score enforced by a direct sanctions match. "
    return f"{lead}This wallet {body}."


def _recommend(band, sanction_hops, mixer_hops, exchange_hops, factors) -> list[str]:
    acts: list[str] = []
    codes = {f.code for f in factors}

    if sanction_hops == 0:
        acts.append("ESCALATE IMMEDIATELY — address is on the OFAC SDN list. Notify FIU-IND and freeze on sight.")
    elif sanction_hops == 1:
        acts.append("One hop from a sanctioned address — escalate for supervisory review before contacting the VASP.")

    if exchange_hops == 0:
        acts.append("Funds deposit DIRECTLY into an exchange — issue a Section 91 BNSS notice to that VASP for KYC and freeze the deposit account.")
    elif exchange_hops is not None and exchange_hops <= 2:
        acts.append(f"Exchange endpoint reachable in {exchange_hops} hops — trace intermediate wallets and prepare VASP notice for terminal address.")
    elif exchange_hops is None:
        acts.append("No exchange endpoint traced yet — increase hop depth or re-run once more of the graph is ingested.")

    if mixer_hops is not None and mixer_hops <= 1:
        acts.append("Mixer exposure — preserve pre-mixer transaction evidence NOW; post-mixer attribution may be unrecoverable.")

    if "PEEL_CHAIN" in codes:
        acts.append("Peel chain detected — map every hop before serving notice, or downstream wallets will be missed.")
    if "FUNNEL_ACCOUNT" in codes:
        acts.append("Collection funnel — cross-check sending addresses against NCRP for other victim complaints.")
    if "BURNER_SWEEP" in codes:
        acts.append("Burner pattern — act quickly; this wallet type is usually abandoned within days.")

    if band in ("critical", "high") and not acts:
        acts.append("High composite risk — assign for manual review and add to watchlist.")
    if band == "low" and not acts:
        acts.append("Low risk — monitor only; no immediate action indicated.")
    return acts


def score_graph(
    edges: list[NormEdge],
    targets: list[str],
    *,
    sanctioned: set[str] | None = None,
    mixers: set[str] | None = None,
    exchanges: set[str] | None = None,
    darknet: set[str] | None = None,
    wallets_intel: dict[str, dict] | None = None,
    initial_amounts: dict[str, float] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """
    Score every wallet AND every transaction in a traced graph using the Fund Attribution Engine.
    Returns (scored_wallets_dict, scored_transactions_list).
    """
    if not edges:
        return {}, []

    sanctioned = sanctioned or set()
    mixers = mixers or set()
    exchanges = exchanges or set()
    darknet = darknet or set()
    target_set = set(targets)
    wallets_intel = wallets_intel or {}

    flags = {
        "sanctioned": list(sanctioned),
        "mixers": list(mixers),
        "exchanges": list(exchanges),
        "darknet": list(darknet),
    }

    # 1. Run Fund Attribution Engine
    edge_attr_map, wallet_attr_map = compute_fund_attribution(
        edges, targets, initial_amounts=initial_amounts
    )

    stats = build_stats(edges)
    h_sanction = _hops_map(edges, sanctioned)
    h_mixer = _hops_map(edges, mixers)
    h_exchange = _hops_map(edges, exchanges)
    h_darknet = _hops_map(edges, darknet)

    # 2. Score every transaction first
    scored_txs: list[dict[str, Any]] = []
    txs_by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for edge in edges:
        sc_tx = score_transaction(
            edge, edges, targets,
            wallets_intel=wallets_intel,
            flags=flags,
            hop_map=h_sanction,
            attr_res=edge_attr_map.get(edge.key),
        )
        scored_txs.append(sc_tx)
        txs_by_wallet[edge.from_address].append(sc_tx)
        txs_by_wallet[edge.to_address].append(sc_tx)

    # 3. Score every wallet, consuming transaction-level risk metrics AND fund attribution
    scored_wallets: dict[str, dict[str, Any]] = {}
    for key, s in stats.items():
        a = s.address
        w_attr = wallet_attr_map.get(key) or wallet_attr_map.get(f"{s.chain}:{a}")
        scored_wallets[a] = score_wallet(
            key, s,
            sanction_hops=h_sanction.get(a),
            mixer_hops=h_mixer.get(a),
            exchange_hops=h_exchange.get(a),
            darknet_hops=h_darknet.get(a),
            peel_depth=_peel_depth(edges, a),
            is_target=a in target_set,
            tx_scores=txs_by_wallet.get(a, []),
            wallets_intel=wallets_intel,
            wallet_attribution=w_attr,
        )

    return scored_wallets, scored_txs


# =====================================================================
# ML FEATURE CONTRACT
# =====================================================================
FEATURE_VERSION = "2.0.0"

FEATURE_ORDER: list[str] = [
    "in_usd", "out_usd", "balance_usd", "pass_through_ratio",
    "log_in_usd", "log_out_usd",
    "tx_count", "fan_in", "fan_out", "fan_ratio", "degree",
    "active_days", "dormancy_days", "tx_per_day",
    "sanction_hops", "mixer_hops", "exchange_hops", "darknet_hops",
    "peel_depth",
    "distinct_assets", "unvalued_ratio", "dust_ratio", "round_ratio",
    "structuring_ratio", "heuristic_score",
]

NO_PATH = 99.0


def _log1p(x: float) -> float:
    return math.log1p(max(x, 0.0))


def feature_vector(score: dict[str, Any]) -> dict[str, float]:
    st = score.get("stats") or {}
    in_usd = float(st.get("inUsd") or 0.0)
    out_usd = float(st.get("outUsd") or 0.0)
    tx = float(st.get("txCount") or 0)
    fan_in = float(st.get("fanIn") or 0)
    fan_out = float(st.get("fanOut") or 0)
    active = float(st.get("activeDays") or 0.0)
    unvalued = float(st.get("unvaluedTransfers") or 0)

    codes = {f.get("code") for f in (score.get("factors") or [])}

    def hop(key: str) -> float:
        v = score.get(key)
        return NO_PATH if v is None else float(v)

    return {
        "in_usd": in_usd,
        "out_usd": out_usd,
        "balance_usd": float(st.get("balanceUsd") or 0.0),
        "pass_through_ratio": (out_usd / in_usd) if in_usd > 0 else 0.0,
        "log_in_usd": _log1p(in_usd),
        "log_out_usd": _log1p(out_usd),
        "tx_count": tx,
        "fan_in": fan_in,
        "fan_out": fan_out,
        "fan_ratio": fan_in / (fan_out + 1.0),
        "degree": fan_in + fan_out,
        "active_days": active,
        "dormancy_days": float(st.get("dormancyDays") or 0.0),
        "tx_per_day": tx / max(active, 1.0),
        "sanction_hops": hop("hops_to_sanctioned"),
        "mixer_hops": hop("hops_to_mixer"),
        "exchange_hops": hop("hops_to_exchange"),
        "darknet_hops": hop("hops_to_darknet"),
        "peel_depth": float(score.get("peel_chain_depth") or 0),
        "distinct_assets": float(len(st.get("assets") or [])),
        "unvalued_ratio": unvalued / max(tx, 1.0),
        "dust_ratio": 1.0 if "DUST_SEEDING" in codes else 0.0,
        "round_ratio": 1.0 if "ADDRESS_POISONING" in codes else 0.0,
        "structuring_ratio": 1.0 if "STRUCTURING" in codes else 0.0,
        "heuristic_score": float(score.get("risk_score") or 0.0),
    }


def feature_matrix(scores: dict[str, dict]) -> tuple[list[str], list[list[float]]]:
    addrs, rows = [], []
    for addr, sc in scores.items():
        fv = feature_vector(sc)
        addrs.append(addr)
        rows.append([fv[k] for k in FEATURE_ORDER])
    return addrs, rows
