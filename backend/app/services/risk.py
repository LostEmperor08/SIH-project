"""
Risk scoring — computed in the gateway, from the traced graph alone.

Why this exists even though there is an ML layer and a SQL detection engine:
both of those need something else to be up. The ML service may be down, and
the SQL engine needs the data already persisted. An officer who pastes an
address must get a scored graph regardless, so this is the always-available
path. When the ML service IS reachable, its scores are merged on top and the
response says which was used.

Every point of the score is attributed to a named factor. A number an
officer cannot explain is useless in a case file — and a risk score that
contributes to freezing someone's assets has to be defensible months later,
in front of someone hostile.

Nothing here is random, seeded, or mocked. Feed it an empty graph and it
returns zero with a reason, not an invented number.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..providers.base import NormEdge

SECONDS_PER_DAY = 86_400.0

# Bands. Deliberately not evenly spaced: the gap between 'medium' and 'high'
# is where an officer's workload changes, so it sits above the midpoint.
BAND_CRITICAL = 80.0
BAND_HIGH = 60.0
BAND_MEDIUM = 35.0


@dataclass
class Factor:
    """One named contribution to the score."""
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
        """1.0 means everything that came in went straight back out."""
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


def _epoch(iso_ts: str) -> float:
    try:
        return datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _hops_map(edges: list[NormEdge], seeds: set[str], max_hops: int = 6) -> dict[str, int]:
    """
    Multi-source BFS outwards from the flagged addresses.

    Running it backwards from the targets turns N single-source searches into
    one traversal — O(E) instead of O(N*E), which is what makes it usable on
    a live graph rather than a toy one.
    """
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
    """
    Look-alike address detection.

    Generating a vanity address that matches a target's first 6 and last 8
    characters is cheap; matching the middle is not. So a group of distinct
    addresses sharing BOTH ends is manufactured, not coincidence — the
    probability of three independent addresses colliding on 14 hex chars is
    vanishingly small.

    EVM only: Bitcoin and Tron addresses are base58 with checksums and do
    not exhibit this pattern the same way.
    """
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
    """
    Longest chain where each hop forwards 70–98% of what it received.

    Value bleeding off a little at a time is the peel chain — the dominant
    layering pattern in task-based and investment fraud. Depth is the signal:
    one hop is ambiguous, eight hops of 90% forwarding is deliberate.
    """
    out: dict[str, list[NormEdge]] = defaultdict(list)
    for e in edges:
        if e.value_usd > 0:
            out[e.from_address].append(e)

    best = 0
    stack: list[tuple[str, float, int, frozenset]] = [(start, math.inf, 0, frozenset([start]))]
    seen_states = 0
    while stack and seen_states < 5000:                # bound the search
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


# =====================================================================
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
) -> dict[str, Any]:
    """Score one wallet. Returns the score plus every factor that fired."""
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

    # ---- structuring: transfers clustered just below a threshold -----
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
    if s.in_usd > 100 and 0.90 <= s.pass_through_ratio <= 1.02 \
            and s.balance_usd < s.in_usd * 0.1:
        add("PASS_THROUGH", "Pass-through wallet", 12,
            f"Forwarded {s.pass_through_ratio:.0%} of everything received, "
            "retaining almost nothing — layering mule",
            ratio=round(s.pass_through_ratio, 3))

    # ---- burner ------------------------------------------------------
    if 0 < s.active_days < 3 and s.fan_in >= 5 and s.pass_through_ratio > 0.85:
        add("BURNER_SWEEP", "Burner wallet", 12,
            f"Collected from {s.fan_in} sources and swept out within "
            f"{s.active_days:.1f} days",
            activeDays=round(s.active_days, 2))

    # ---- dormant then active ------------------------------------------
    if s.active_days > 90 and s.dormancy_days < 3 and s.tx_count > 5:
        add("DORMANT_BURST", "Dormant-then-burst", 8,
            "Long-dormant wallet suddenly active again — reactivated mule",
            dormancyDays=round(s.dormancy_days, 1))

    # ---- address poisoning --------------------------------------------
    # Found in live data: four senders to one wallet, all sharing the same
    # crafted 6-char prefix AND 8-char suffix, one of them sending dust.
    # The attacker generates vanity addresses that look like a real
    # counterparty, seeds the victim's history, and waits for them to copy
    # the wrong one from their wallet app. PS 26183's victim scenario
    # exactly — so the tool should name it rather than leave an officer to
    # spot four near-identical hex strings by eye.
    poison = _detect_poisoning(s.senders | s.receivers)
    if poison:
        add("ADDRESS_POISONING", "Address-poisoning cluster", 18,
            f"transacts with {poison['count']} counterparties sharing the "
            f"crafted pattern {poison['prefix']}…{poison['suffix']} — look-alike "
            "addresses seeded so the victim copies the wrong one",
            **poison)

    if s.values:
        dust = sum(1 for v in s.values if 0 < v < 0.01)
        if dust and poison:
            add("DUST_SEEDING", "Dust seeding", 6,
                f"{dust} near-zero transfer(s) alongside look-alike addresses "
                "— the bait transaction of a poisoning attack",
                dustTransfers=dust)

    # ---- exchange proximity -------------------------------------------
    # Not itself suspicious — it is the ACTIONABLE part. A direct deposit
    # means there is a VASP to serve a notice on, which raises priority
    # without implying the exchange did anything wrong.
    if exchange_hops == 0 and not is_target:
        add("EXCHANGE_ENDPOINT", "Exchange deposit endpoint", 5,
            "Funds deposit directly into an exchange — freezable endpoint",
            hops=0)

    total = min(100.0, sum(f.points for f in factors))
    # A direct sanctions hit pins the score. A model or heuristic may raise
    # an alarm; it is never allowed to talk one down.
    floor_applied = False
    if sanction_hops == 0:
        total = max(total, 90.0)
        floor_applied = True

    band = ("critical" if total >= BAND_CRITICAL else
            "high" if total >= BAND_HIGH else
            "medium" if total >= BAND_MEDIUM else "low")

    return {
        "address": s.address,
        "chain": s.chain,
        "risk_score": round(total, 2),
        "risk_band": band,
        "sanction_floor_applied": floor_applied,
        "factors": [
            {"code": f.code, "label": f.label, "points": f.points,
             "detail": f.detail, "evidence": f.evidence}
            for f in sorted(factors, key=lambda x: -x.points)
        ],
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
            # honest signalling: how much of this wallet's activity we could
            # not price, so nobody reads a low USD figure as low activity
            "unvaluedTransfers": s.unvalued_count,
        },
        "narrative": _narrate(s, factors, total, band),
        "recommended_actions": _recommend(
            band, sanction_hops, mixer_hops, exchange_hops, factors),
    }


# =====================================================================
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
    """
    Investigative next steps — an explicit PS 26183 deliverable.

    Phrased as actions for an officer, never as conclusions. The system
    proposes; a human decides.
    """
    acts: list[str] = []
    codes = {f.code for f in factors}

    if sanction_hops == 0:
        acts.append("ESCALATE IMMEDIATELY — address is on the OFAC SDN list. "
                    "Notify FIU-IND and freeze on sight.")
    elif sanction_hops == 1:
        acts.append("One hop from a sanctioned address — escalate for "
                    "supervisory review before contacting the VASP.")

    if exchange_hops == 0:
        acts.append("Funds deposit DIRECTLY into an exchange — issue a Section 91 "
                    "BNSS notice to that VASP for KYC and freeze the deposit account.")
    elif exchange_hops is not None and exchange_hops <= 2:
        acts.append(f"Exchange endpoint reachable in {exchange_hops} hops — trace the "
                    "intermediate wallets and prepare a VASP notice for the terminal address.")
    elif exchange_hops is None:
        acts.append("No exchange endpoint traced yet — increase hop depth or "
                    "re-run once more of the graph is ingested.")

    if mixer_hops is not None and mixer_hops <= 1:
        acts.append("Mixer exposure — preserve pre-mixer transaction evidence NOW; "
                    "post-mixer attribution may be unrecoverable.")

    if "PEEL_CHAIN" in codes:
        acts.append("Peel chain detected — map every hop before serving notice, "
                    "or the downstream wallets will be missed.")
    if "FUNNEL_ACCOUNT" in codes:
        acts.append("Collection funnel — cross-check the sending addresses against "
                    "NCRP for other victim complaints in the same campaign.")
    if "BURNER_SWEEP" in codes:
        acts.append("Burner pattern — act quickly; this wallet type is usually "
                    "abandoned within days.")

    if band in ("critical", "high") and not acts:
        acts.append("High composite risk — assign for manual review and add to watchlist.")
    if band == "low" and not acts:
        acts.append("Low risk — monitor only; no immediate action indicated.")
    return acts


# =====================================================================
def score_graph(
    edges: list[NormEdge],
    targets: list[str],
    *,
    sanctioned: set[str] | None = None,
    mixers: set[str] | None = None,
    exchanges: set[str] | None = None,
    darknet: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Score every wallet in a traced graph. address -> score dict.

    The always-available path: no database, no ML service, no network.
    """
    if not edges:
        return {}

    sanctioned = sanctioned or set()
    mixers = mixers or set()
    exchanges = exchanges or set()
    darknet = darknet or set()
    target_set = set(targets)

    stats = build_stats(edges)
    h_sanction = _hops_map(edges, sanctioned)
    h_mixer = _hops_map(edges, mixers)
    h_exchange = _hops_map(edges, exchanges)
    h_darknet = _hops_map(edges, darknet)

    out: dict[str, dict[str, Any]] = {}
    for key, s in stats.items():
        a = s.address
        out[a] = score_wallet(
            key, s,
            sanction_hops=h_sanction.get(a),
            mixer_hops=h_mixer.get(a),
            exchange_hops=h_exchange.get(a),
            darknet_hops=h_darknet.get(a),
            peel_depth=_peel_depth(edges, a),
            is_target=a in target_set,
        )
    return out


# =====================================================================
# ML FEATURE CONTRACT
#
# This is the single source of truth for what the model sees. Before this
# existed there were two definitions — aiml/src/features/schema.py and the
# stats computed here — which is the classic training/serving skew: the
# model scores 0.95 offline and produces nonsense in production because the
# serving path built a column differently.
#
# Now the ML trains on EXACTLY what /trace computes, because it trains on
# /trace's own output. There is nothing to keep in sync.
# =====================================================================

# Order is part of the contract: a model is a positional array of floats.
# Append only — never reorder or delete, or an old model silently reads the
# wrong column. Bump FEATURE_VERSION when you append.
FEATURE_VERSION = "1.0.0"

FEATURE_ORDER: list[str] = [
    # flow
    "in_usd", "out_usd", "balance_usd", "pass_through_ratio",
    "log_in_usd", "log_out_usd",
    # shape
    "tx_count", "fan_in", "fan_out", "fan_ratio", "degree",
    # time
    "active_days", "dormancy_days", "tx_per_day",
    # proximity (99 = no path found — a real observation, not missing data)
    "sanction_hops", "mixer_hops", "exchange_hops", "darknet_hops",
    "peel_depth",
    # composition
    "distinct_assets", "unvalued_ratio", "dust_ratio", "round_ratio",
    "structuring_ratio",
    # the heuristic verdict itself, as a feature the model may agree or
    # disagree with — it learns where the rules are wrong
    "heuristic_score",
]

NO_PATH = 99.0


def _log1p(x: float) -> float:
    return math.log1p(max(x, 0.0))


def feature_vector(score: dict[str, Any]) -> dict[str, float]:
    """
    Turn one wallet's score dict (from score_graph) into a flat numeric
    feature map. Deterministic, no I/O, no randomness.
    """
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
        # these three are carried as binary evidence that the rule fired;
        # the model can learn to weight them differently than the rules do
        "dust_ratio": 1.0 if "DUST_SEEDING" in codes else 0.0,
        "round_ratio": 1.0 if "ADDRESS_POISONING" in codes else 0.0,
        "structuring_ratio": 1.0 if "STRUCTURING" in codes else 0.0,
        "heuristic_score": float(score.get("risk_score") or 0.0),
    }


def feature_matrix(scores: dict[str, dict]) -> tuple[list[str], list[list[float]]]:
    """scores (address -> score dict) -> (addresses, rows) in FEATURE_ORDER."""
    addrs, rows = [], []
    for addr, sc in scores.items():
        fv = feature_vector(sc)
        addrs.append(addr)
        rows.append([fv[k] for k in FEATURE_ORDER])
    return addrs, rows
