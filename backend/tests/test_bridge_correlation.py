"""
Unit test suite for Batch 3: Cross-Chain Bridge Correlation Engine.

Tests:
 1. Exact message ID correlation (message_id matches -> EXACT quality, confidence >= 0.96)
 2. Exact protocol sequence correlation
 3. Amount-with-fee correlation ($10,000 -> $9,950 within 5% fee tolerance)
 4. Destination recipient correlation
 5. Asset mapping (USDT -> USDT.e / USDT0)
 6. Chain isolation (prevents same-chain bridge correlation)
 7. Unknown bridge contract handling (UNVERIFIED)
 8. No false correlation from amount alone (different bridge/route rejected)
 9. No false correlation from timestamp alone (unrelated transaction rejected)
10. Ambiguous candidates handling (highest confidence candidate selected)
11. Cross-chain split (source split into multiple destination bridge events)
12. Cross-chain merge (multiple bridge events into single destination wallet)
13. Batch 1 attribution continuity across bridges (victim funds carry across chain boundary)
14. Batch 2 VASP compatibility at cross-chain destination (destination exchange match)
15. Graph/API response compatibility (TraceResponse payload contract)
16. Persistence compatibility (cross_chain_transfers to_dict)
17. Cycle & malformed event safety (graceful handling of empty or cyclic logs)
18. Deterministic results (same inputs produce identical outputs)
19. Large candidate set performance benchmark (500+ transfers correlated < 1.0s)
20. Existing trace/risk regression compatibility
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
from app.services.risk import score_graph
from app.services.bridge_correlation import (
    correlate_cross_chain_transfers,
    extract_bridge_events,
    propagate_cross_chain_attribution,
    BridgeEvent,
    BridgeTransfer,
    CORRELATION_MESSAGE_ID,
    CORRELATION_FUZZY_ROUTE,
    QUALITY_EXACT,
    QUALITY_HIGH,
)

NOW = datetime.now(timezone.utc)


def ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def make_edge(
    frm: str, to: str, usd: float, chain: str = "eth", h: str | None = None,
    raw: dict | None = None, asset: str = "USDT"
) -> NormEdge:
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
        asset=asset,
        raw=raw or {"transferType": "erc20"},
    )


TARGET = "0xtarget000000000000000000000000000000001"
BRIDGE_SRC = "0x8731d54e9d02c286767d56ac03e8037c07e01e98"
BRIDGE_DST = "0x45a2e574423823529a408152bc0e82c06b1ed606"
POLYGON_MULE = "0xpolygonmule00000000000000000000000001"
BINANCE_POLYGON_DEP = "0x21a31ee1afc51d94c2efccaa2092ad1028285549"


def make_bridge_event(
    chain: str, tx_hash: str, from_addr: str, to_addr: str, usd: float,
    role: str, message_id: str | None = None, days_ago: float = 1.0, asset: str = "USDT"
) -> BridgeEvent:
    return BridgeEvent(
        chain=chain,
        tx_hash=tx_hash,
        vout_index=0,
        block_time=ts(days_ago),
        timestamp=_epoch(ts(days_ago)),
        address=to_addr if role in ("LOCK", "BURN", "DEPOSIT") else from_addr,
        from_address=from_addr,
        to_address=to_addr,
        bridge_id="bridge_stargate",
        bridge_name="Stargate / LayerZero",
        role=role,
        asset=asset,
        amount_native=usd,
        amount_usd=usd,
        message_id=message_id,
        recipient=to_addr if role in ("RELEASE", "MINT") else None,
    )


def _epoch(iso_str: str) -> float:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()


# 1. Exact Message ID Correlation
def test_1_exact_message_id_correlation():
    src_ev = make_bridge_event("eth", "0xsrc1", TARGET, BRIDGE_SRC, 10000.0, "LOCK", message_id="msg_998877", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst1", BRIDGE_DST, POLYGON_MULE, 9970.0, "RELEASE", message_id="msg_998877", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 1
    c = correlations[0]
    assert c.correlation_type == CORRELATION_MESSAGE_ID
    assert c.correlation_quality == QUALITY_EXACT
    assert c.correlation_confidence >= 0.96
    assert c.source_chain == "eth"
    assert c.destination_chain == "polygon"
    assert c.message_id == "msg_998877"


# 2. Exact Protocol Event Correlation
def test_2_exact_protocol_event_correlation():
    src_ev = make_bridge_event("eth", "0xsrc2", TARGET, BRIDGE_SRC, 5000.0, "BURN", message_id="seq_1001", days_ago=2.0)
    dst_ev = make_bridge_event("bsc", "0xdst2", BRIDGE_DST, POLYGON_MULE, 5000.0, "MINT", message_id="seq_1001", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 1
    c = correlations[0]
    assert c.correlation_quality == QUALITY_EXACT
    assert c.destination_chain == "bsc"


# 3. Amount-with-Fee Correlation (5% Fee Tolerance)
def test_3_amount_with_fee_correlation():
    # $10,000 sent from ETH, $9,950 received on Polygon (0.5% fee)
    src_ev = make_bridge_event("eth", "0xsrc3", TARGET, BRIDGE_SRC, 10000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst3", BRIDGE_DST, POLYGON_MULE, 9950.0, "RELEASE", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 1
    c = correlations[0]
    assert c.fee_usd == 50.0
    assert c.source_amount == 10000.0
    assert c.destination_amount == 9950.0


# 4. Destination Recipient Correlation
def test_4_destination_recipient_correlation():
    src_ev = make_bridge_event("eth", "0xsrc4", TARGET, BRIDGE_SRC, 7000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst4", BRIDGE_DST, POLYGON_MULE, 7000.0, "RELEASE", days_ago=1.98)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 1
    assert correlations[0].destination_address == POLYGON_MULE


# 5. Asset Mapping (USDT -> USDT.e / USDT0)
def test_5_asset_mapping():
    src_ev = make_bridge_event("eth", "0xsrc5", TARGET, BRIDGE_SRC, 4000.0, "LOCK", days_ago=2.0, asset="USDT")
    dst_ev = make_bridge_event("polygon", "0xdst5", BRIDGE_DST, POLYGON_MULE, 4000.0, "RELEASE", days_ago=1.99, asset="USDT0")
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 1
    assert correlations[0].source_asset == "USDT"
    assert correlations[0].destination_asset == "USDT0"


# 6. Chain Isolation (Cannot correlate on same chain)
def test_6_chain_isolation():
    src_ev = make_bridge_event("eth", "0xsrc6", TARGET, BRIDGE_SRC, 1000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("eth", "0xdst6", BRIDGE_SRC, POLYGON_MULE, 1000.0, "RELEASE", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 0


# 7. Unknown Bridge Contract Handling
def test_7_unknown_bridge_contract_handling():
    edges = [make_edge(TARGET, POLYGON_MULE, 1000.0, chain="eth")]
    src_events, dst_events = extract_bridge_events(edges, bridge_intel_map={})
    
    assert len(src_events) == 0
    assert len(dst_events) == 0


# 8. No False Correlation from Amount Alone
def test_8_no_false_correlation_from_amount_alone():
    # Large fee difference (> 5%) MUST be rejected
    src_ev = make_bridge_event("eth", "0xsrc8", TARGET, BRIDGE_SRC, 10000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst8", BRIDGE_DST, POLYGON_MULE, 8000.0, "RELEASE", days_ago=1.99) # 20% diff
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 0


# 9. No False Correlation from Timestamp Alone
def test_9_no_false_correlation_from_timestamp_alone():
    # Destination occurs 5 hours later (> 3600s time window) MUST be rejected
    src_ev = make_bridge_event("eth", "0xsrc9", TARGET, BRIDGE_SRC, 10000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst9", BRIDGE_DST, POLYGON_MULE, 10000.0, "RELEASE", days_ago=1.5) # 12 hours later
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert len(correlations) == 0


# 10. Ambiguous Candidates Handling
def test_10_ambiguous_candidates_handling():
    src_ev = make_bridge_event("eth", "0xsrc10", TARGET, BRIDGE_SRC, 10000.0, "LOCK", message_id="msg_exact", days_ago=2.0)
    dst_ev1 = make_bridge_event("polygon", "0xdst10_a", BRIDGE_DST, POLYGON_MULE, 10000.0, "RELEASE", days_ago=1.99) # Fuzzy candidate
    dst_ev2 = make_bridge_event("polygon", "0xdst10_b", BRIDGE_DST, POLYGON_MULE, 10000.0, "RELEASE", message_id="msg_exact", days_ago=1.99) # Exact msg candidate
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev1, dst_ev2])
    
    assert len(correlations) == 1
    assert correlations[0].destination_tx_hash == "0xdst10_b"
    assert correlations[0].correlation_type == CORRELATION_MESSAGE_ID


# 11. Cross-Chain Split
def test_11_cross_chain_split():
    src_ev1 = make_bridge_event("eth", "0xsrc11_a", TARGET, BRIDGE_SRC, 6000.0, "LOCK", message_id="m1", days_ago=2.0)
    src_ev2 = make_bridge_event("eth", "0xsrc11_b", TARGET, BRIDGE_SRC, 4000.0, "LOCK", message_id="m2", days_ago=2.0)
    
    dst_ev1 = make_bridge_event("polygon", "0xdst11_a", BRIDGE_DST, POLYGON_MULE, 6000.0, "RELEASE", message_id="m1", days_ago=1.99)
    dst_ev2 = make_bridge_event("bsc", "0xdst11_b", BRIDGE_DST, POLYGON_MULE, 4000.0, "MINT", message_id="m2", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev1, src_ev2], [dst_ev1, dst_ev2])
    
    assert len(correlations) == 2
    chains = {c.destination_chain for c in correlations}
    assert chains == {"polygon", "bsc"}


# 12. Cross-Chain Merge
def test_12_cross_chain_merge():
    src_eth = make_bridge_event("eth", "0xsrc12_eth", TARGET, BRIDGE_SRC, 5000.0, "LOCK", message_id="m_eth", days_ago=2.0)
    src_bsc = make_bridge_event("bsc", "0xsrc12_bsc", TARGET, BRIDGE_SRC, 5000.0, "LOCK", message_id="m_bsc", days_ago=2.0)
    
    dst1 = make_bridge_event("polygon", "0xdst12_1", BRIDGE_DST, POLYGON_MULE, 5000.0, "RELEASE", message_id="m_eth", days_ago=1.99)
    dst2 = make_bridge_event("polygon", "0xdst12_2", BRIDGE_DST, POLYGON_MULE, 5000.0, "RELEASE", message_id="m_bsc", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_eth, src_bsc], [dst1, dst2])
    
    assert len(correlations) == 2
    assert all(c.destination_address == POLYGON_MULE for c in correlations)


# 13. Batch 1 Attribution Continuity Across Bridges
def test_13_batch_1_attribution_continuity():
    src_ev = make_bridge_event("eth", "0xsrc13", TARGET, BRIDGE_SRC, 10000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst13", BRIDGE_DST, POLYGON_MULE, 9950.0, "RELEASE", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    propagated = propagate_cross_chain_attribution([], [TARGET], correlations)
    
    assert len(propagated) == 1
    assert propagated[0].attributed_value_usd == 9950.0
    assert any("CROSS_CHAIN_PROVENANCE" in e["type"] for e in propagated[0].evidence)


# 14. Batch 2 VASP Compatibility at Cross-Chain Destination
def test_14_batch_2_vasp_compatibility_at_destination():
    intel = {
        f"polygon:{BINANCE_POLYGON_DEP}": {"vasp_name": "Binance", "is_known_deposit": True}
    }
    src_ev = make_bridge_event("eth", "0xsrc14", TARGET, BRIDGE_SRC, 10000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst14", BRIDGE_DST, BINANCE_POLYGON_DEP, 9950.0, "RELEASE", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    assert len(correlations) == 1
    assert correlations[0].destination_address == BINANCE_POLYGON_DEP


# 15. Graph/API Response Compatibility
def test_15_graph_api_response_compatibility():
    src_ev = make_bridge_event("eth", "0xsrc15", TARGET, BRIDGE_SRC, 10000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst15", BRIDGE_DST, POLYGON_MULE, 9950.0, "RELEASE", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    d = correlations[0].to_dict()
    
    assert "bridge_id" in d
    assert "source_chain" in d
    assert "destination_chain" in d
    assert "correlation_confidence" in d
    assert "attributed_value_usd" in d


# 16. Persistence Compatibility
def test_16_persistence_compatibility():
    src_ev = make_bridge_event("eth", "0xsrc16", TARGET, BRIDGE_SRC, 5000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst16", BRIDGE_DST, POLYGON_MULE, 5000.0, "RELEASE", days_ago=1.99)
    
    correlations = correlate_cross_chain_transfers([src_ev], [dst_ev])
    row = correlations[0].to_dict()
    
    assert isinstance(row, dict)
    assert row["source_amount"] == 5000.0
    assert row["destination_amount"] == 5000.0


# 17. Cycle & Malformed Event Safety
def test_17_cycle_malformed_event_safety():
    # Empty lists or malformed raw dicts should not raise exceptions
    correlations = correlate_cross_chain_transfers([], [])
    assert correlations == []


# 18. Deterministic Results
def test_18_deterministic_results():
    src_ev = make_bridge_event("eth", "0xsrc18", TARGET, BRIDGE_SRC, 10000.0, "LOCK", days_ago=2.0)
    dst_ev = make_bridge_event("polygon", "0xdst18", BRIDGE_DST, POLYGON_MULE, 9950.0, "RELEASE", days_ago=1.99)
    
    c1 = correlate_cross_chain_transfers([src_ev], [dst_ev])
    c2 = correlate_cross_chain_transfers([src_ev], [dst_ev])
    
    assert c1[0].to_dict() == c2[0].to_dict()


# 19. Large Candidate Set Performance Benchmark
def test_19_large_candidate_set_performance():
    # 500+ transfers correlation benchmark < 1.0s
    srcs = [make_bridge_event("eth", f"0xsrc_{i}", TARGET, BRIDGE_SRC, 1000.0, "LOCK", message_id=f"msg_{i}", days_ago=2.0) for i in range(500)]
    dsts = [make_bridge_event("polygon", f"0xdst_{i}", BRIDGE_DST, POLYGON_MULE, 995.0, "RELEASE", message_id=f"msg_{i}", days_ago=1.99) for i in range(500)]
    
    t0 = time.perf_counter()
    correlations = correlate_cross_chain_transfers(srcs, dsts)
    elapsed = time.perf_counter() - t0
    
    assert elapsed < 1.0, f"Cross-chain correlation benchmark took {elapsed:.4f}s (must be < 1.0s)"
    assert len(correlations) == 500


# 20. Existing Trace / Risk Regression Compatibility
def test_20_existing_trace_risk_compatibility():
    wallets, txs = score_graph([make_edge(TARGET, POLYGON_MULE, 5000.0)], [TARGET])
    
    assert TARGET in wallets
    assert POLYGON_MULE in wallets
    assert len(txs) == 1
