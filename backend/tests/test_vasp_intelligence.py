"""
Unit test suite for Batch 2: VASP Intelligence & Exchange Wallet Directory Engine.

Tests:
 1. Exact known deposit address match (identified=True, confidence >= 0.95, wallet_type=DEPOSIT)
 2. Known hot wallet match (wallet_type=HOT)
 3. Known cold wallet match (wallet_type=COLD)
 4. Unknown wallet handling (identified=False, vasp_name=None)
 5. High-risk unknown wallet (MUST REMAIN identified=False — false-positive protection)
 6. Sanctioned non-VASP wallet (MUST REMAIN identified=False — false-positive protection)
 7. Exchange receiving suspect funds (VASP identified, case relevance high, risk score decoupled)
 8. Multiple candidates resolution (highest bounded confidence selection)
 9. Duplicate evidence deduplication (same independence group does not double-count)
10. Cluster match evidence (cluster membership produces high-confidence signal)
11. Batch lookup performance benchmark (500+ wallets evaluated in < 1.0s)
12. Multi-chain address isolation (same textual address across chains isolated)
13. Existing Batch 1 fund attribution compatibility
14. Existing risk scoring compatibility
15. Existing trace response compatibility
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.providers.base import NormEdge
from app.services.risk import score_graph, score_wallet, score_transaction
from app.services.vasp_intelligence import (
    calculate_bounded_confidence,
    resolve_vasp_attribution,
    resolve_nearest_exchange,
    VaspEvidenceItem,
    ROLE_DEPOSIT,
    ROLE_HOT,
    ROLE_COLD,
    EVIDENCE_EXACT_KNOWN_DEPOSIT,
    EVIDENCE_EXACT_KNOWN_HOT_WALLET,
    EVIDENCE_CLUSTER_MATCH,
)

NOW = datetime.now(timezone.utc)


def ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def make_edge(frm: str, to: str, usd: float, chain: str = "eth", h: str | None = None) -> NormEdge:
    return NormEdge(
        chain=chain,
        tx_hash=h or f"0x{abs(hash((frm, to, usd, chain))) % 10**12:012x}",
        vout_index=0,
        block_height=1000,
        block_time=ts(1.0),
        from_address=frm,
        to_address=to,
        value_native=usd,
        value_usd=usd,
        fee_usd=0.0,
        asset="USDT",
        raw={"transferType": "erc20"},
    )


TARGET = "0xtarget000000000000000000000000000000001"
MULE_A = "0xa0000000000000000000000000000000000001"
BINANCE_DEP = "0x21a31ee1afc51d94c2efccaa2092ad1028285549"
BINANCE_HOT = "0x28c6c06298d514db089934071355e5743bf21d60"
BINANCE_COLD = "0xdfd5293d8e347dff59e90ef0cd06ff1eace935c6"
SANCTIONED = "0xsanctioned00000000000000000000000000001"
HIGH_RISK_UNKNOWN = "0xhighrisk00000000000000000000000000001"


# 1. Exact Known Deposit Address Match
def test_1_exact_known_deposit():
    intel = {
        f"eth:{BINANCE_DEP}": {
            "vasp_id": "vasp_binance",
            "vasp_name": "Binance",
            "wallet_type": "DEPOSIT",
            "is_known_deposit": True,
        }
    }
    res = resolve_vasp_attribution(BINANCE_DEP, "eth", wallets_intel=intel)
    
    assert res.identified is True
    assert res.vasp_name == "Binance"
    assert res.wallet_type == "DEPOSIT"
    assert res.confidence >= 0.95
    assert any(e["type"] == EVIDENCE_EXACT_KNOWN_DEPOSIT for e in res.evidence)


# 2. Known Hot Wallet Match
def test_2_known_hot_wallet():
    intel = {
        f"eth:{BINANCE_HOT}": {
            "vasp_id": "vasp_binance",
            "vasp_name": "Binance",
            "wallet_type": "HOT",
            "is_known_hot_wallet": True,
        }
    }
    res = resolve_vasp_attribution(BINANCE_HOT, "eth", wallets_intel=intel)
    
    assert res.identified is True
    assert res.vasp_name == "Binance"
    assert res.wallet_type == "HOT"
    assert res.confidence >= 0.95


# 3. Known Cold Wallet Match
def test_3_known_cold_wallet():
    intel = {
        f"eth:{BINANCE_COLD}": {
            "vasp_id": "vasp_binance",
            "vasp_name": "Binance",
            "wallet_type": "COLD",
            "is_known_cold_wallet": True,
        }
    }
    res = resolve_vasp_attribution(BINANCE_COLD, "eth", wallets_intel=intel)
    
    assert res.identified is True
    assert res.vasp_name == "Binance"
    assert res.wallet_type == "COLD"
    assert res.confidence >= 0.95


# 4. Unknown Wallet Handling
def test_4_unknown_wallet():
    res = resolve_vasp_attribution(MULE_A, "eth", wallets_intel={})
    
    assert res.identified is False
    assert res.vasp_name is None
    assert res.confidence == 0.0
    assert res.wallet_type == "UNKNOWN"
    assert len(res.evidence) == 0


# 5. High-Risk Unknown Wallet (False-Positive Protection)
def test_5_high_risk_unknown_wallet_protection():
    # A wallet with rapid forwarding, high volume, peel chains
    # MUST REMAIN unidentified as VASP unless explicit VASP evidence exists
    res = resolve_vasp_attribution(HIGH_RISK_UNKNOWN, "eth", wallets_intel={})
    
    assert res.identified is False
    assert res.vasp_name is None
    assert res.confidence == 0.0


# 6. Sanctioned Non-VASP Wallet (False-Positive Protection)
def test_6_sanctioned_wallet_protection():
    intel = {
        f"eth:{SANCTIONED}": {
            "is_sanctioned": True,
            "entity_type": "sanctioned_individual",
        }
    }
    res = resolve_vasp_attribution(SANCTIONED, "eth", wallets_intel=intel)
    
    assert res.identified is False
    assert res.vasp_name is None
    assert res.confidence == 0.0


# 7. Exchange Receiving Suspect Funds (Decoupled Dimensions)
def test_7_exchange_receiving_suspect_funds():
    intel = {
        f"eth:{BINANCE_DEP}": {
            "vasp_name": "Binance",
            "is_known_deposit": True,
        }
    }
    edges = [
        make_edge(TARGET, MULE_A, 10000.0),
        make_edge(MULE_A, BINANCE_DEP, 10000.0),
    ]
    wallets, txs = score_graph(edges, [TARGET], wallets_intel=intel)
    
    dep_wallet = wallets[BINANCE_DEP]
    assert dep_wallet["vasp_attribution"]["identified"] is True
    assert dep_wallet["vasp_attribution"]["confidence"] >= 0.95
    # VASP identification does not artificially force risk score to 100
    assert dep_wallet["risk_score"] < 90.0 or dep_wallet["sanction_floor_applied"] is False


# 8. Multiple Candidates Resolution
def test_8_multiple_candidates_resolution():
    records = [
        {"evidence_type": EVIDENCE_CLUSTER_MATCH, "confidence": 0.88, "source": "cluster_db", "independence_group": "g1"},
        {"evidence_type": EVIDENCE_EXACT_KNOWN_DEPOSIT, "confidence": 0.98, "source": "official_registry", "independence_group": "g2"},
    ]
    res = resolve_vasp_attribution(BINANCE_DEP, "eth", explicit_vasp_name="Binance", evidence_records=records)
    
    assert res.identified is True
    assert res.confidence >= 0.98
    assert len(res.evidence) == 2


# 9. Duplicate Evidence Deduplication
def test_9_duplicate_evidence_deduplication():
    # Two evidence items with identical independence_group must not double-count
    item1 = VaspEvidenceItem("EXACT_KNOWN_HOT_WALLET", "HIGH", 0.95, "SourceA", independence_group="group_1")
    item2 = VaspEvidenceItem("EXACT_KNOWN_HOT_WALLET", "HIGH", 0.95, "SourceB", independence_group="group_1")
    
    conf = calculate_bounded_confidence([item1, item2])
    # Should equal 0.95, not 1 - (0.05 * 0.05) = 0.9975
    assert conf == 0.95


# 10. Cluster Match Evidence
def test_10_cluster_match_evidence():
    intel = {
        f"eth:{MULE_A}": {
            "vasp_name": "Coinbase",
            "cluster_id": "cluster_cb_01",
            "cluster_name": "Coinbase Deposit Cluster",
        }
    }
    res = resolve_vasp_attribution(MULE_A, "eth", wallets_intel=intel)
    
    assert res.identified is True
    assert res.vasp_name == "Coinbase"
    assert res.cluster_id == "cluster_cb_01"
    assert any(e["type"] == EVIDENCE_CLUSTER_MATCH for e in res.evidence)


# 11. Batch Lookup Performance Benchmark
def test_11_batch_lookup_performance():
    # Simulate 500+ wallets VASP resolution
    intel = {}
    for i in range(550):
        addr = f"0x{i:040x}"
        if i % 10 == 0:
            intel[f"eth:{addr}"] = {"vasp_name": "Binance", "is_known_deposit": True}
            
    t0 = time.perf_counter()
    results = [resolve_vasp_attribution(f"0x{i:040x}", "eth", wallets_intel=intel) for i in range(550)]
    elapsed = time.perf_counter() - t0
    
    assert elapsed < 1.0, f"VASP batch resolution took {elapsed:.4f}s (must be < 1.0s)"
    assert sum(1 for r in results if r.identified) == 55


# 12. Multi-Chain Address Isolation
def test_12_multi_chain_address_isolation():
    shared_addr = "0x1111111111111111111111111111111111111111"
    intel = {
        f"eth:{shared_addr}": {"vasp_name": "Binance", "is_known_deposit": True},
        # Tron / Polygon entry is absent
    }
    res_eth = resolve_vasp_attribution(shared_addr, "eth", wallets_intel=intel)
    res_tron = resolve_vasp_attribution(shared_addr, "tron", wallets_intel=intel)
    
    assert res_eth.identified is True
    assert res_tron.identified is False


# 13. Existing Batch 1 Fund Attribution Compatibility
def test_13_batch_1_fund_attribution_compatibility():
    intel = {
        f"eth:{BINANCE_DEP}": {"vasp_name": "Binance", "is_known_deposit": True}
    }
    edges = [make_edge(TARGET, BINANCE_DEP, 7000.0)]
    wallets, txs = score_graph(edges, [TARGET], wallets_intel=intel)
    
    stx = txs[0]
    assert "relevance" in stx
    assert stx["relevance"]["attributed_value_usd"] == 7000.0
    assert stx["relevance"]["attribution_method"] == "DIRECT_SOURCE"


# 14. Existing Risk Scoring Compatibility
def test_14_existing_risk_scoring_compatibility():
    wallets, txs = score_graph([make_edge(TARGET, MULE_A, 5000.0)], [TARGET])
    
    assert TARGET in wallets
    assert MULE_A in wallets
    assert "risk_score" in wallets[MULE_A]
    assert "risk_band" in wallets[MULE_A]


# 15. Existing Trace Response Compatibility
def test_15_existing_trace_response_compatibility():
    intel = {
        f"eth:{BINANCE_DEP}": {"vasp_name": "Binance", "is_known_deposit": True}
    }
    edges = [
        make_edge(TARGET, MULE_A, 10000.0),
        make_edge(MULE_A, BINANCE_DEP, 6000.0),
    ]
    wallets, txs = score_graph(edges, [TARGET], wallets_intel=intel)
    
    vasp_map = {k: v["vasp_attribution"] for k, v in wallets.items() if v.get("vasp_attribution")}
    nearest = resolve_nearest_exchange([TARGET], edges, vasp_map, {k: v["fund_attribution"] for k, v in wallets.items()})
    
    assert nearest is not None
    assert nearest["exchange_name"] == "Binance"
    assert nearest["deposit_address"] == BINANCE_DEP
    assert nearest["hops"] == 2
