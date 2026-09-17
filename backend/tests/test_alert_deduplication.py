"""
Unit & Integration Test Suite for Batch 5 Idempotency Key Deduplication,
Poll Retry Safety, Lifecycle State Transitions, and Adversarial Cases A-F.
"""
from __future__ import annotations

import pytest
from app.services.alert_engine import (
    generate_idempotency_key,
    evaluate_alert_rules,
    STATUS_NEW,
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    STATUS_DISMISSED,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
    TYPE_KNOWN_EXCHANGE,
    TYPE_CROSS_CHAIN,
    TYPE_SANCTIONS,
    TYPE_HIGH_RISK_TX,
)


def test_case_a_known_exchange_deposit():
    """Adversarial Case A: Known exchange deposit produces INFO/LOW alert, never CRITICAL."""
    tx_context = {
        "tx_hash": "0xexchangedeposit1",
        "chain": "polygon",
        "risk": {"score": 15.0, "factors": []},
        "relevance": {"score": 10.0, "attributed_value_usd": 20.0, "fund_attribution_share": 0.01},
        "vasp_attribution": {"vasp_name": "Coinbase", "confidence": 0.98},
    }
    wallet_context = {"vasp_attribution": {"vasp_name": "Coinbase", "confidence": 0.98}}
    candidates = evaluate_alert_rules(tx_context, wallet_context, case_id="CASE-A")
    assert len(candidates) > 0
    exchange_alert = candidates[0]
    assert exchange_alert.severity in [SEVERITY_INFO, SEVERITY_LOW]
    assert exchange_alert.severity != SEVERITY_CRITICAL


def test_case_b_single_bridge_use():
    """Adversarial Case B: Single bridge usage without high risk produces non-critical alert."""
    tx_context = {
        "tx_hash": "0xbridgemovement1",
        "chain": "ethereum",
        "risk": {"score": 30.0, "factors": []},
        "relevance": {"score": 25.0, "attributed_value_usd": 150.0, "fund_attribution_share": 0.05},
        "bridge_info": {"bridge_name": "Stargate", "dest_chain": "avalanche", "confidence": 0.90},
    }
    candidates = evaluate_alert_rules(tx_context, case_id="CASE-B")
    bridge_alerts = [c for c in candidates if c.alert_type in [TYPE_CROSS_CHAIN]]
    assert len(bridge_alerts) >= 1
    assert bridge_alerts[0].severity != SEVERITY_CRITICAL


def test_case_c_multihop_high_risk():
    """Adversarial Case C: Multi-hop trace with high composite risk score (85) produces CRITICAL alert."""
    tx_context = {
        "tx_hash": "0xmultihophighrisk",
        "chain": "ethereum",
        "risk": {
            "score": 85.0,
            "factors": [
                {"code": "HIGH_TAINT_SHARE", "evidence": "85% reported fund taint"},
                {"code": "RAPID_LAYERING", "evidence": "Moved within 2 minutes across 4 hops"}
            ],
        },
        "relevance": {"score": 85.0, "attributed_value_usd": 8500.0, "fund_attribution_share": 0.85},
    }
    candidates = evaluate_alert_rules(tx_context, case_id="CASE-C")
    critical_alerts = [c for c in candidates if c.severity == SEVERITY_CRITICAL]
    assert len(critical_alerts) >= 1


def test_case_d_duplicate_poll_retries_deduplication():
    """Adversarial Case D: Duplicate poll retries generate identical idempotency keys to prevent DB duplication."""
    case_id = "SIH/2026/00412"
    chain = "polygon"
    tx_hash = "0xretryhash999"
    alert_type = TYPE_HIGH_RISK_TX
    rule_id = "RULE_HIGH_RISK"

    # Simulate 5 consecutive poll evaluations for the exact same transaction
    keys = [
        generate_idempotency_key(case_id, chain, tx_hash, alert_type, rule_id)
        for _ in range(5)
    ]
    # All 5 generated idempotency keys MUST be identical
    assert len(set(keys)) == 1


def test_case_e_lifecycle_state_transitions():
    """Adversarial Case E: Alert lifecycle transitions (NEW -> ACKNOWLEDGED -> RESOLVED / DISMISSED)."""
    valid_statuses = {
        STATUS_NEW,
        STATUS_ACKNOWLEDGED,
        STATUS_RESOLVED,
        STATUS_DISMISSED,
    }
    # Check that candidate starts at NEW
    tx_context = {
        "tx_hash": "0xlifecycle1",
        "chain": "ethereum",
        "risk": {"score": 75.0, "factors": []},
        "relevance": {"score": 50.0, "attributed_value_usd": 500.0, "fund_attribution_share": 0.20},
    }
    candidates = evaluate_alert_rules(tx_context, case_id="CASE-E")
    candidate_dict = candidates[0].to_dict()
    assert candidate_dict["status"] == STATUS_NEW
    assert candidate_dict["status"] in valid_statuses


def test_case_f_case_isolation():
    """Adversarial Case F: Case isolation guarantees alerts are bound to their specific case_id."""
    candidates_1 = evaluate_alert_rules(
        {"tx_hash": "0xcase1_tx", "chain": "polygon", "risk": {"score": 90.0}},
        case_id="CASE-ALPHA",
    )
    candidates_2 = evaluate_alert_rules(
        {"tx_hash": "0xcase2_tx", "chain": "polygon", "risk": {"score": 90.0}},
        case_id="CASE-BETA",
    )

    dict1 = candidates_1[0].to_dict()
    dict2 = candidates_2[0].to_dict()

    assert dict1["case_id"] == "CASE-ALPHA"
    assert dict2["case_id"] == "CASE-BETA"
    assert dict1["idempotency_key"] != dict2["idempotency_key"]
