"""
Unit test suite for Batch 1: Recursive Fund Attribution & Taint Propagation Engine.

Tests:
 1. Direct transfer (target -> A, $10,000)
 2. 2-way split (target -> A $6,000, target -> B $4,000)
 3. Recursive downstream (target -> A $10,000 -> B $6,000 -> C $4,000)
 4. Mixed wallet pro-rata allocation (70% tainted balance -> 50% send -> 35% attributed)
 5. Merge (target1 -> C $6,000, target2 -> C $4,000)
 6. Split then merge (target -> A $6,000 & B $4,000; A -> C $3,000, B -> C $2,000)
 7. Double counting protection (attribution bounded by original source pool)
 8. Cycle safety (A -> B -> C -> A loop detection and clean termination)
 9. Multiple assets isolation (ETH vs USDT isolated in (chain, asset) pools)
10. Missing data handling (unattributed sender -> UNAVAILABLE method & quality)
11. Determinism (same inputs, shuffled order -> identical output)
12. Large graph performance benchmark (500+ edges executed < 1s)
13. Existing risk score compatibility (score_graph integration)
14. Existing trace compatibility (score_transaction contract)
"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.providers.base import NormEdge
from app.services.fund_attribution import compute_fund_attribution
from app.services.risk import score_graph, score_transaction, score_wallet

NOW = datetime.now(timezone.utc)


def ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def make_edge(
    frm: str, to: str, usd: float, days_ago: float = 1.0,
    asset: str = "USDT", chain: str = "eth", h: str | None = None
) -> NormEdge:
    return NormEdge(
        chain=chain,
        tx_hash=h or f"0x{abs(hash((frm, to, usd, days_ago, asset, chain))) % 10**12:012x}",
        vout_index=0,
        block_height=1000,
        block_time=ts(days_ago),
        from_address=frm,
        to_address=to,
        value_native=usd,
        value_usd=usd,
        fee_usd=0.0,
        asset=asset,
        raw={"transferType": "erc20"},
    )


TARGET = "0xtarget000000000000000000000000000000001"
TARGET2 = "0xtarget000000000000000000000000000000002"
ADDR_A = "0xa0000000000000000000000000000000000001"
ADDR_B = "0xb0000000000000000000000000000000000002"
ADDR_C = "0xc0000000000000000000000000000000000003"
ADDR_D = "0xd0000000000000000000000000000000000004"
CLEAN_SRC = "0xclean000000000000000000000000000000001"


# 1. Direct Transfer
def test_1_direct_transfer():
    edges = [make_edge(TARGET, ADDR_A, 10000.0, days_ago=2.0)]
    edge_attributions, wallet_attributions = compute_fund_attribution(edges, [TARGET])
    
    edge_key = edges[0].key
    assert edge_key in edge_attributions
    ea = edge_attributions[edge_key]
    
    assert ea.attributed_value_usd == 10000.0
    assert ea.attribution_method == "DIRECT_SOURCE"
    assert ea.attribution_quality == "DIRECT"
    assert len(ea.provenance_paths) == 1
    assert TARGET in ea.provenance_paths[0]["path"] and ADDR_A in ea.provenance_paths[0]["path"]


# 2. Two-Way Split
def test_2_two_way_split():
    e1 = make_edge(TARGET, ADDR_A, 6000.0, days_ago=2.0)
    e2 = make_edge(TARGET, ADDR_B, 4000.0, days_ago=1.9)
    edge_attributions, wallet_attributions = compute_fund_attribution([e1, e2], [TARGET])
    
    ea1 = edge_attributions[e1.key]
    ea2 = edge_attributions[e2.key]
    
    assert ea1.attributed_value_usd == 6000.0
    assert ea1.attribution_method == "DIRECT_SOURCE"
    assert ea2.attributed_value_usd == 4000.0
    assert ea2.attribution_method == "DIRECT_SOURCE"
    
    wa = wallet_attributions[f"eth:{ADDR_A}"]
    wb = wallet_attributions[f"eth:{ADDR_B}"]
    assert wa.attributed_inbound_usd == 6000.0
    assert wb.attributed_inbound_usd == 4000.0


# 3. Recursive Downstream (Multi-Hop)
def test_3_recursive_downstream():
    e1 = make_edge(TARGET, ADDR_A, 10000.0, days_ago=3.0)
    e2 = make_edge(ADDR_A, ADDR_B, 6000.0, days_ago=2.0)
    e3 = make_edge(ADDR_B, ADDR_C, 4000.0, days_ago=1.0)
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e1, e2, e3], [TARGET])
    
    ea1 = edge_attributions[e1.key]
    ea2 = edge_attributions[e2.key]
    ea3 = edge_attributions[e3.key]
    
    assert ea1.attributed_value_usd == 10000.0
    assert ea2.attributed_value_usd == 6000.0
    assert ea3.attributed_value_usd == 4000.0
    
    path_str = ea3.provenance_paths[0]["path"]
    assert TARGET in path_str and ADDR_A in path_str and ADDR_B in path_str and ADDR_C in path_str


# 4. Mixed Wallet Pro-Rata Allocation
def test_4_mixed_wallet_pro_rata():
    # ADDR_A gets 7000 from TARGET and 3000 from CLEAN_SRC (Total = 10000, Taint ratio = 0.70)
    e1 = make_edge(TARGET, ADDR_A, 7000.0, days_ago=4.0)
    e_clean = make_edge(CLEAN_SRC, ADDR_A, 3000.0, days_ago=3.5)
    # ADDR_A sends 5000 to ADDR_B
    e_out = make_edge(ADDR_A, ADDR_B, 5000.0, days_ago=2.0)
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e1, e_clean, e_out], [TARGET])
    
    ea_out = edge_attributions[e_out.key]
    # 5000 * (7000/10000) = 3500.0 attributed USD
    assert ea_out.attributed_value_usd == pytest.approx(3500.0, rel=0.01)
    assert ea_out.attribution_method == "PRO_RATA"
    assert ea_out.attribution_quality in ("HIGH", "MEDIUM")


# 5. Merge (Multiple Victims -> Single Wallet)
def test_5_merge():
    e1 = make_edge(TARGET, ADDR_C, 6000.0, days_ago=2.0)
    e2 = make_edge(TARGET2, ADDR_C, 4000.0, days_ago=1.8)
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e1, e2], [TARGET, TARGET2])
    
    wc = wallet_attributions[f"eth:{ADDR_C}"]
    assert wc.attributed_inbound_usd == 10000.0
    assert len(wc.participating_sources) == 2
    assert set(wc.participating_sources) == {TARGET, TARGET2}


# 6. Split Then Merge
def test_6_split_then_merge():
    # Target -> A (6k) & B (4k)
    e1 = make_edge(TARGET, ADDR_A, 6000.0, days_ago=3.0)
    e2 = make_edge(TARGET, ADDR_B, 4000.0, days_ago=2.9)
    # A -> C (3k), B -> C (2k)
    e3 = make_edge(ADDR_A, ADDR_C, 3000.0, days_ago=2.0)
    e4 = make_edge(ADDR_B, ADDR_C, 2000.0, days_ago=1.9)
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e1, e2, e3, e4], [TARGET])
    
    wc = wallet_attributions[f"eth:{ADDR_C}"]
    assert wc.attributed_inbound_usd == 5000.0


# 7. Double Counting Protection
def test_7_double_counting_protection():
    # Target starts with 10k
    e1 = make_edge(TARGET, ADDR_A, 10000.0, days_ago=3.0)
    # A attempts to send 15000 (more than received) to B
    e2 = make_edge(ADDR_A, ADDR_B, 15000.0, days_ago=2.0)
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e1, e2], [TARGET])
    
    ea2 = edge_attributions[e2.key]
    # Attributed value cannot exceed what A possessed (10,000 USD)
    assert ea2.attributed_value_usd <= 10000.0


# 8. Cycle Safety
def test_8_cycle_safety():
    # A -> B -> C -> A (Cycle)
    e1 = make_edge(TARGET, ADDR_A, 10000.0, days_ago=4.0)
    e2 = make_edge(ADDR_A, ADDR_B, 8000.0, days_ago=3.0)
    e3 = make_edge(ADDR_B, ADDR_C, 8000.0, days_ago=2.0)
    e4 = make_edge(ADDR_C, ADDR_A, 8000.0, days_ago=1.0) # Loop back to A
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e1, e2, e3, e4], [TARGET])
    
    ea4 = edge_attributions[e4.key]
    # Loop back edge should be rejected due to cycle prevention
    assert ea4.attributed_value_usd == 0.0 or len(ea4.provenance_paths) == 0


# 9. Multiple Assets Isolation
def test_9_multiple_assets_isolation():
    # Target sends 10000 USDT and 10 ETH to A
    e_usdt = make_edge(TARGET, ADDR_A, 10000.0, days_ago=2.0, asset="USDT")
    e_eth = make_edge(TARGET, ADDR_A, 30000.0, days_ago=2.0, asset="ETH")
    
    # A sends 5000 USDT to B
    e_out_usdt = make_edge(ADDR_A, ADDR_B, 5000.0, days_ago=1.0, asset="USDT")
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e_usdt, e_eth, e_out_usdt], [TARGET])
    
    ea_out = edge_attributions[e_out_usdt.key]
    # USDT pool should be evaluated independently from ETH pool
    assert ea_out.attributed_value_usd == 5000.0


# 10. Missing Data Handling (Unattributed Sender)
def test_10_missing_data_handling():
    # CLEAN_SRC -> ADDR_A (No target connection)
    e1 = make_edge(CLEAN_SRC, ADDR_A, 5000.0, days_ago=2.0)
    edge_attributions, wallet_attributions = compute_fund_attribution([e1], [TARGET])
    
    ea1 = edge_attributions[e1.key]
    assert ea1.attributed_value_usd == 0.0
    assert ea1.attribution_method == "UNAVAILABLE"
    assert ea1.attribution_quality == "UNAVAILABLE"


# 11. Determinism
def test_11_determinism():
    edges = [
        make_edge(TARGET, ADDR_A, 10000.0, days_ago=5.0, h="0x1"),
        make_edge(ADDR_A, ADDR_B, 6000.0, days_ago=4.0, h="0x2"),
        make_edge(ADDR_A, ADDR_C, 4000.0, days_ago=3.0, h="0x3"),
        make_edge(ADDR_B, ADDR_D, 3000.0, days_ago=2.0, h="0x4"),
    ]
    
    res1_edges, _ = compute_fund_attribution(edges, [TARGET])
    
    # Shuffle edge order
    shuffled = list(edges)
    random.seed(42)
    random.shuffle(shuffled)
    
    res2_edges, _ = compute_fund_attribution(shuffled, [TARGET])
    
    for e in edges:
        ea1 = res1_edges[e.key]
        ea2 = res2_edges[e.key]
        assert ea1.attributed_value_usd == ea2.attributed_value_usd
        assert ea1.attribution_method == ea2.attribution_method
        assert ea1.attribution_quality == ea2.attribution_quality


# 12. Large Graph Performance Benchmark
def test_12_large_graph_performance():
    # Build a graph with 500+ edges
    edges = []
    current_layer = [TARGET]
    
    tx_count = 0
    days = 10.0
    for hop in range(3):
        next_layer = []
        for i, node in enumerate(current_layer):
            for child_idx in range(8):
                child_addr = f"0xnode_{hop}_{i}_{child_idx}".ljust(42, "0")
                next_layer.append(child_addr)
                days -= 0.001
                edges.append(make_edge(node, child_addr, 1000.0, days_ago=days, h=f"0xtx_{tx_count}"))
                tx_count += 1
        current_layer = next_layer
        
    assert len(edges) >= 500
    
    t0 = time.perf_counter()
    edge_attributions, wallet_attributions = compute_fund_attribution(edges, [TARGET])
    elapsed = time.perf_counter() - t0
    
    assert elapsed < 1.0, f"Attribution benchmark took {elapsed:.4f}s (must be < 1.0s)"
    assert len(edge_attributions) == len(edges)


# 13. Existing Risk Score Compatibility
def test_13_existing_risk_score_compatibility():
    e1 = make_edge(TARGET, ADDR_A, 10000.0, days_ago=2.0)
    wallets, txs = score_graph([e1], [TARGET])
    
    assert TARGET in wallets
    assert ADDR_A in wallets
    assert len(txs) == 1
    
    stx = txs[0]
    assert "relevance" in stx
    rel = stx["relevance"]
    assert "attributed_value_usd" in rel
    assert "attribution_method" in rel
    assert "attribution_quality" in rel
    assert rel["attributed_value_usd"] == 10000.0


# 14. Existing Trace Compatibility
def test_14_existing_trace_compatibility():
    e1 = make_edge(TARGET, ADDR_A, 10000.0, days_ago=2.0)
    
    edge_attributions, wallet_attributions = compute_fund_attribution([e1], [TARGET])
    scored_tx = score_transaction(e1, [e1], [TARGET], attr_res=edge_attributions[e1.key])
    
    assert scored_tx["from_address"] == TARGET
    assert scored_tx["to_address"] == ADDR_A
    assert scored_tx["amount_usd"] == 10000.0
    assert "risk" in scored_tx
    assert "relevance" in scored_tx
    assert scored_tx["relevance"]["score"] == 95.0
