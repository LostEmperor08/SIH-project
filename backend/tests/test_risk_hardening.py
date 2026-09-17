"""
Comprehensive Unit & Adversarial Test Suite for Batch 4 — Risk Engine Hardening,
Contextual Intelligence & ML Validation (SIH 2026 Problem Statement 26183).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from app.providers.base import NormEdge
from app.services.risk import (
    score_transaction,
    score_wallet,
    score_graph,
    tx_risk_band,
    wallet_risk_band,
    calculate_vasp_attribution_confidence,
    build_stats,
    feature_vector,
    RISK_ENGINE_VERSION,
)


def _make_edge(
    from_addr: str,
    to_addr: str,
    val_usd: float = 1000.0,
    chain: str = "polygon",
    tx_hash: str = "0xhash",
    block_time: str = "2026-03-31T10:00:00Z",
) -> NormEdge:
    return NormEdge(
        chain=chain,
        tx_hash=tx_hash,
        vout_index=0,
        block_height=100000,
        block_time=block_time,
        from_address=from_addr,
        to_address=to_addr,
        value_native=val_usd,
        value_usd=val_usd,
        fee_usd=0.01,
        asset="USDT",
    )


# =====================================================================
# 1. DECOUPLING INVARIANTS
# =====================================================================
def test_decoupling_risk_not_equal_relevance():
    """Case relevance must remain independent of risk score."""
    edge = _make_edge("0xvictim", "0xexchange", val_usd=10000.0)
    all_edges = [edge]
    targets = ["0xvictim"]
    flags = {"exchanges": ["0xexchange"]}
    attr = {
        "attribution_share": 1.0,
        "attributed_value_usd": 10000.0,
        "attribution_method": "DIRECT",
        "attribution_quality": "DIRECT",
        "provenance_paths": [["0xvictim", "0xexchange"]],
    }

    res = score_transaction(
        edge, all_edges, targets, flags=flags, attr_res=attr, hop_map={"0xexchange": 1}
    )
    # Relevance is high (direct victim transfer to exchange)
    assert res["relevance"]["score"] >= 60.0
    # Risk is bounded (20 pts for fund attribution)
    assert res["risk"]["score"] <= 35.0
    assert res["risk"]["score"] != res["relevance"]["score"]


def test_decoupling_risk_not_equal_vasp_confidence():
    """VASP confidence (0-1.0) must not equal risk_score / 100."""
    vasp_intel = {
        "polygon:0xbinance_dep": {
            "entity_type": "exchange",
            "vasp_name": "Binance",
            "wallet_type": "DEPOSIT",
            "confidence": 0.88,
        }
    }
    conf = calculate_vasp_attribution_confidence(
        "0xbinance_dep", "polygon", wallets_intel=vasp_intel
    )
    assert conf is not None
    assert conf["confidence"] == 0.88
    # Ensure VASP attribution does not generate a fake 88 risk score
    s = build_stats([_make_edge("0xa", "0xbinance_dep")])["polygon:0xbinance_dep"]
    w_sc = score_wallet(
        "polygon:0xbinance_dep", s,
        sanction_hops=None, mixer_hops=None, exchange_hops=0, darknet_hops=None,
        peel_depth=0, is_target=False, wallets_intel=vasp_intel
    )
    assert w_sc["risk_score"] < 50.0


def test_decoupling_risk_not_equal_bridge_confidence():
    """Bridge correlation confidence must not inflate transaction risk into critical."""
    edge = _make_edge("0xa", "0xbridge_contract", val_usd=50000.0)
    all_edges = [edge]
    flags = {"bridges": ["0xbridge_contract"]}

    res = score_transaction(edge, all_edges, targets=["0xa"], flags=flags)
    # Ordinary bridge transition adds only minor points (2 pts)
    assert res["risk"]["score"] <= 35.0
    assert res["risk"]["band"] in ("LOW", "MODERATE", "ELEVATED")


def test_decoupling_risk_not_equal_fund_attribution():
    """100% fund attribution does not force a 100 risk score."""
    edge = _make_edge("0xvictim", "0xbystander", val_usd=5000.0)
    all_edges = [edge]
    attr = {
        "attribution_share": 1.0,
        "attributed_value_usd": 5000.0,
        "attribution_method": "DIRECT",
        "attribution_quality": "DIRECT",
        "provenance_paths": [["0xvictim", "0xbystander"]],
    }

    res = score_transaction(edge, all_edges, targets=["0xvictim"], attr_res=attr)
    assert res["relevance"]["fund_attribution_share"] == 1.0
    # Risk factor contribution is bounded (20 pts for fund linkage)
    assert res["risk"]["score"] <= 30.0


# =====================================================================
# 2. FACTOR BOUNDS & DOUBLE-COUNTING AUDIT
# =====================================================================
def test_factor_bounds_and_total_capped_at_100():
    """Total risk score must never exceed 100.0."""
    edge = _make_edge("0xa", "0xb", val_usd=9000.0)
    all_edges = [edge] * 20
    flags = {
        "sanctioned": ["0xa"],
        "mixers": ["0xb"],
        "darknet": ["0xb"],
        "illicit": ["0xb"],
    }
    res = score_transaction(edge, all_edges, targets=["0xa"], flags=flags)
    assert res["risk"]["score"] <= 100.0


def test_missing_data_safety():
    """Missing timestamps or null values must degrade gracefully without crashing."""
    edge = NormEdge(
        chain="polygon",
        tx_hash="0xnull",
        vout_index=0,
        block_height=None,
        block_time="2026-03-31T10:00:00Z",
        from_address="0xnull_sender",
        to_address="0xnull_recv",
        value_native=0.0,
        value_usd=0.0,
        fee_usd=0.0,
        asset="USDT",
    )
    res = score_transaction(edge, [edge], targets=["0xnull_sender"])
    assert res["risk"]["score"] >= 0.0
    assert isinstance(res["risk"]["factors"], list)


def test_small_samples_anomaly_safety():
    """Modified Z-score with less than 3 transactions returns 0 anomaly points safely."""
    edge = _make_edge("0xa", "0xb", val_usd=1000.0)
    res = score_transaction(edge, [edge], targets=["0xa"])
    # No anomaly factor should fire for n=1 sample
    anomaly_factors = [f for f in res["risk"]["factors"] if "ANOMALY" in f["code"]]
    assert len(anomaly_factors) == 0


# =====================================================================
# 3. TRANSACTION & WALLET RISK SCORING
# =====================================================================
def test_rapid_forwarding_velocity_factor():
    """Forwarding 90% of funds 30s after receipt triggers rapid pass-through factor."""
    e1 = _make_edge("0xsource", "0xmiddle", val_usd=10000.0, block_time="2026-03-31T10:00:00Z")
    e2 = _make_edge("0xmiddle", "0xdest", val_usd=9500.0, block_time="2026-03-31T10:00:30Z")
    all_edges = [e1, e2]

    res = score_transaction(e2, all_edges, targets=["0xsource"])
    factor_codes = [f["code"] for f in res["risk"]["factors"]]
    assert "RAPID_PASS_THROUGH" in factor_codes


def test_structuring_near_threshold_factor():
    """Transfers clustered between $8,000 and $9,999 trigger structuring factor."""
    edges = [
        _make_edge("0xa", "0xb", val_usd=9500.0, tx_hash=f"0x{i}") for i in range(5)
    ]
    res = score_transaction(edges[0], edges, targets=["0xa"])
    factor_codes = [f["code"] for f in res["risk"]["factors"]]
    assert any("STRUCTURING" in code for code in factor_codes)


def test_bounded_wallet_aggregation():
    """Wallet risk aggregation must be bounded and reflect distribution stats."""
    e1 = _make_edge("0xmule", "0xd1", val_usd=5000.0)
    e2 = _make_edge("0xmule", "0xd2", val_usd=8000.0)
    edges = [e1, e2]
    stats = build_stats(edges)["polygon:0xmule"]

    w_sc = score_wallet(
        "polygon:0xmule", stats,
        sanction_hops=None, mixer_hops=None, exchange_hops=None, darknet_hops=None,
        peel_depth=2, is_target=False
    )
    assert 0.0 <= w_sc["risk_score"] <= 100.0
    assert "transaction_aggregates" in w_sc
    assert "structured_alert_events" in w_sc


# =====================================================================
# 4. SANCTIONS HARD FLOOR SAFEGUARDS
# =====================================================================
def test_sanctions_hard_floor_wallet():
    """Direct sanctions match on wallet forces minimum 90.0 CRITICAL score."""
    e = _make_edge("0xsanctioned_wallet", "0xb")
    stats = build_stats([e])["polygon:0xsanctioned_wallet"]

    w_sc = score_wallet(
        "polygon:0xsanctioned_wallet", stats,
        sanction_hops=0, mixer_hops=None, exchange_hops=None, darknet_hops=None,
        peel_depth=0, is_target=False
    )
    assert w_sc["risk_score"] >= 90.0
    assert w_sc["risk_band"] == "critical"
    assert w_sc["sanction_floor_applied"] is True
    assert w_sc["sanction_source"] == "OFAC_SDN_LIST"


def test_sanctions_hard_floor_transaction():
    """Direct sanctions match on transaction forces minimum 90.0 CRITICAL score."""
    edge = _make_edge("0xa", "0xsanctioned_recv")
    flags = {"sanctioned": ["0xsanctioned_recv"]}

    res = score_transaction(edge, [edge], targets=["0xa"], flags=flags)
    assert res["risk"]["score"] >= 90.0
    assert res["risk"]["band"] == "CRITICAL"
    assert res["risk"]["sanction_floor_applied"] is True


# =====================================================================
# 5. ADVERSARIAL TEST CASES
# =====================================================================
def test_adversarial_case_a_known_exchange_large_volume():
    """Case A: Known exchange + large volume + high tx count must NOT get high risk."""
    e = _make_edge("0xlegit_user", "0xbinance_hot", val_usd=500000.0)
    flags = {"exchanges": ["0xbinance_hot"]}
    intel = {"polygon:0xbinance_hot": {"entity_type": "exchange", "vasp_name": "Binance"}}

    res = score_transaction(e, [e], targets=["0xlegit_user"], flags=flags, wallets_intel=intel)
    assert res["risk"]["score"] <= 40.0
    assert res["risk"]["band"] in ("LOW", "MODERATE", "ELEVATED")


def test_adversarial_case_b_bridge_usage_large_transfer():
    """Case B: Bridge usage + large transfer must NOT automatically receive critical risk."""
    e = _make_edge("0xuser", "0xstargate_router", val_usd=250000.0)
    flags = {"bridges": ["0xstargate_router"]}

    res = score_transaction(e, [e], targets=["0xuser"], flags=flags)
    assert res["risk"]["score"] <= 45.0
    assert res["risk"]["band"] != "CRITICAL"


def test_adversarial_case_c_high_fund_attribution_alone():
    """Case C: 100% fund attribution alone must NOT produce > 30 risk score."""
    e = _make_edge("0xvictim", "0xclean_merchant", val_usd=1000.0)
    attr = {
        "attribution_share": 1.0,
        "attributed_value_usd": 1000.0,
        "attribution_method": "DIRECT",
        "attribution_quality": "DIRECT",
        "provenance_paths": [["0xvictim", "0xclean_merchant"]],
    }

    res = score_transaction(e, [e], targets=["0xvictim"], attr_res=attr)
    assert res["risk"]["score"] <= 30.0


def test_adversarial_case_d_high_risk_wallet_no_false_vasp():
    """Case D: High-risk wallet must NOT be attributed as a VASP unless in exchange directory."""
    e = _make_edge("0xscammer", "0xmule")
    stats = build_stats([e])["polygon:0xmule"]

    w_sc = score_wallet(
        "polygon:0xmule", stats,
        sanction_hops=1, mixer_hops=0, exchange_hops=None, darknet_hops=None,
        peel_depth=6, is_target=False
    )
    assert w_sc["risk_score"] >= 70.0
    # Must NOT create fake VASP attribution
    assert w_sc["vasp_attribution"] is None


def test_adversarial_case_e_vasp_confidence_does_not_force_risk_98():
    """Case E: VASP confidence 0.88 must NOT equal risk 88."""
    intel = {"polygon:0xkraken": {"entity_type": "exchange", "vasp_name": "Kraken", "confidence": 0.88}}
    conf = calculate_vasp_attribution_confidence("0xkraken", "polygon", wallets_intel=intel)
    assert conf["confidence"] == 0.88

    e = _make_edge("0xa", "0xkraken")
    stats = build_stats([e])["polygon:0xkraken"]
    w_sc = score_wallet(
        "polygon:0xkraken", stats,
        sanction_hops=None, mixer_hops=None, exchange_hops=0, darknet_hops=None,
        peel_depth=0, is_target=False, wallets_intel=intel
    )
    assert w_sc["risk_score"] != 88.0
    assert w_sc["risk_score"] < 50.0


def test_adversarial_case_f_sanctions_floor_cannot_be_lowered():
    """Case F: Sanctions floor cannot be lowered by ML or heuristics."""
    e = _make_edge("0xsanctioned_wallet", "0xb")
    stats = build_stats([e])["polygon:0xsanctioned_wallet"]

    w_sc = score_wallet(
        "polygon:0xsanctioned_wallet", stats,
        sanction_hops=0, mixer_hops=None, exchange_hops=None, darknet_hops=None,
        peel_depth=0, is_target=False
    )
    assert w_sc["risk_score"] >= 90.0
    assert w_sc["sanction_floor_applied"] is True


# =====================================================================
# 6. FEATURE CONTRACT & GRAPH INTEGRATION
# =====================================================================
def test_feature_vector_extraction():
    """Feature vector extraction must be point-in-time safe and return all schema keys."""
    e = _make_edge("0xa", "0xb", val_usd=5000.0)
    stats = build_stats([e])["polygon:0xa"]
    w_sc = score_wallet(
        "polygon:0xa", stats,
        sanction_hops=None, mixer_hops=None, exchange_hops=None, darknet_hops=None,
        peel_depth=0, is_target=True
    )
    fv = feature_vector(w_sc)
    assert "in_usd" in fv
    assert "out_usd" in fv
    assert "heuristic_score" in fv
    assert fv["heuristic_score"] == w_sc["risk_score"]


def test_score_graph_integration():
    """score_graph must return scored wallets dict and scored transactions list."""
    e1 = _make_edge("0xvictim", "0xlayer1", val_usd=10000.0)
    e2 = _make_edge("0xlayer1", "0xexchange", val_usd=9500.0)
    edges = [e1, e2]

    scored_wallets, scored_txs = score_graph(
        edges, targets=["0xvictim"],
        exchanges={"0xexchange"}
    )
    assert len(scored_wallets) >= 3
    assert len(scored_txs) == 2
    assert "0xvictim" in scored_wallets
    assert "0xexchange" in scored_wallets
    assert scored_wallets["0xexchange"]["hops_to_exchange"] == 0
    assert scored_wallets["0xexchange"]["engine_version"] == RISK_ENGINE_VERSION
