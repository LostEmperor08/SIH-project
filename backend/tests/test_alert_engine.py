"""
Unit & Integration Test Suite for Batch 5 Alert Engine Rule Evaluation & Severity.
"""
from __future__ import annotations

import pytest
from app.services.alert_engine import (
    evaluate_alert_rules,
    generate_idempotency_key,
    AlertCandidate,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
    TYPE_SANCTIONS,
    TYPE_CRITICAL_TX,
    TYPE_HIGH_RISK_TX,
    TYPE_LARGE_FUND,
    TYPE_KNOWN_EXCHANGE,
    TYPE_CROSS_CHAIN,
    TYPE_BRIDGE_CORRELATION,
)


def test_idempotency_key_generation():
    """Idempotency key is deterministic across case, chain, tx_hash, alert_type, rule_id."""
    key1 = generate_idempotency_key(
        case_id="SIH/2026/00412",
        chain="polygon",
        tx_hash="0xABC123",
        alert_type=TYPE_HIGH_RISK_TX,
        rule_id="RULE_HIGH_RISK",
    )
    key2 = generate_idempotency_key(
        case_id="SIH/2026/00412",
        chain="POLYGON",  # test case insensitivity
        tx_hash="0xabc123",
        alert_type=TYPE_HIGH_RISK_TX,
        rule_id="RULE_HIGH_RISK",
    )
    assert key1 == key2
    assert len(key1) == 32


def test_sanctions_match_forces_critical():
    """Verified sanctions match forces mandatory CRITICAL alert regardless of risk score."""
    tx_context = {
        "tx_hash": "0xsanctions123",
        "chain": "ethereum",
        "risk": {
            "score": 40.0,
            "sanction_floor_applied": True,
            "factors": [{"code": "SANCTIONS_EXPOSURE", "evidence": "OFAC SDN List Match"}],
        },
        "relevance": {"score": 30.0, "attributed_value_usd": 100.0, "fund_attribution_share": 0.05},
    }
    candidates = evaluate_alert_rules(tx_context=tx_context, case_id="CASE-001")
    assert len(candidates) >= 1
    sanctions_alert = next((c for c in candidates if c.alert_type == TYPE_SANCTIONS), None)
    assert sanctions_alert is not None
    assert sanctions_alert.severity == SEVERITY_CRITICAL
    assert sanctions_alert.risk_score >= 90.0


def test_known_exchange_deposit_non_critical():
    """Known exchange deposit without high risk/fund attribution produces INFO/LOW alert, NOT critical."""
    tx_context = {
        "tx_hash": "0xbinance_deposit",
        "chain": "ethereum",
        "risk": {
            "score": 25.0,
            "factors": [{"code": "KNOWN_EXCHANGE", "evidence": "Binance Hot Wallet"}],
        },
        "relevance": {"score": 20.0, "attributed_value_usd": 50.0, "fund_attribution_share": 0.02},
        "vasp_attribution": {
            "vasp_name": "Binance",
            "confidence": 0.95,
        }
    }
    wallet_context = {
        "vasp_attribution": {
            "vasp_name": "Binance",
            "confidence": 0.95,
        }
    }
    candidates = evaluate_alert_rules(tx_context=tx_context, wallet_context=wallet_context, case_id="CASE-002")
    exchange_alerts = [c for c in candidates if c.alert_type == TYPE_KNOWN_EXCHANGE]
    assert len(exchange_alerts) == 1
    # Check severity is INFO or LOW, definitely NOT CRITICAL or HIGH
    assert exchange_alerts[0].severity in [SEVERITY_INFO, SEVERITY_LOW]
    assert exchange_alerts[0].severity != SEVERITY_CRITICAL
    assert exchange_alerts[0].severity != SEVERITY_HIGH


def test_bridge_correlation_non_critical_without_high_risk():
    """Single bridge usage without high risk or large fund attribution produces non-critical alert."""
    tx_context = {
        "tx_hash": "0xbridge_deposit",
        "chain": "ethereum",
        "risk": {
            "score": 35.0,
            "factors": [{"code": "CROSS_CHAIN_BRIDGE", "evidence": "Hop Protocol Bridge Deposit"}],
        },
        "relevance": {"score": 30.0, "attributed_value_usd": 200.0, "fund_attribution_share": 0.10},
        "bridge_info": {
            "bridge_name": "Hop Protocol",
            "dest_chain": "polygon",
            "confidence": 0.88,
        }
    }
    candidates = evaluate_alert_rules(tx_context=tx_context, case_id="CASE-003")
    bridge_alerts = [c for c in candidates if c.alert_type in [TYPE_CROSS_CHAIN, TYPE_BRIDGE_CORRELATION]]
    assert len(bridge_alerts) >= 1
    for alert in bridge_alerts:
        assert alert.severity != SEVERITY_CRITICAL


def test_large_attributed_fund_movement():
    """Large victim reported fund movement ($5000+) triggers HIGH severity alert."""
    tx_context = {
        "tx_hash": "0xlarge_fund_tx",
        "chain": "polygon",
        "risk": {
            "score": 50.0,
            "factors": [],
        },
        "relevance": {"score": 75.0, "attributed_value_usd": 6500.0, "fund_attribution_share": 0.65},
    }
    candidates = evaluate_alert_rules(tx_context=tx_context, case_id="CASE-004")
    large_fund_alert = next((c for c in candidates if c.alert_type == TYPE_LARGE_FUND), None)
    assert large_fund_alert is not None
    assert large_fund_alert.severity == SEVERITY_HIGH
    assert large_fund_alert.attributed_value_usd == 6500.0
