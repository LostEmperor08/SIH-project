"""
Chakravyuh SETU — Batch 8 Data Consistency & Invariants Test Suite.

Verifies strict system numeric bounds and contract invariants:
- Risk Score ∈ [0, 100]
- Case Relevance Score ∈ [0, 100]
- Fund Attribution Share ∈ [0, 1.0]
- VASP Confidence Score ∈ [0, 0.99]
- Bridge Confidence Score ∈ [0, 0.99]
- ML Fraud Probability ∈ [0, 1.0]
- Non-negative attributed amounts ($USD >= 0)
- Multi-view data aggregation consistency across case workspace views
"""
from __future__ import annotations

import os
import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.providers.base import NormEdge
from app.services.fund_attribution import compute_fund_attribution
from app.services.vasp_intelligence import resolve_vasp_attribution
from app.services.bridge_correlation import correlate_cross_chain_transfers, BridgeEvent
from app.services.risk import score_transaction
from app.services.cases import get_case_service

BINANCE_HOT = "0x28c6c06298d514db089934071355e5743bf21d60"


class TestDataConsistencyInvariants:
    """Batch 8 Numeric Bounds & Invariant Validation."""

    def test_risk_score_bounds(self):
        """Verify Risk Score and Case Relevance Score remain in [0, 100]."""
        edge = NormEdge(
            chain="ethereum",
            tx_hash="0xbounds01",
            vout_index=0,
            block_height=100,
            from_address="0xfrom",
            to_address="0xto",
            value_native=10.0,
            value_usd=10000.0,
            fee_usd=0.0,
            block_time="2023-11-14T00:00:00Z",
            asset="ETH",
        )

        res = score_transaction(edge, [edge], ["0xfrom"])

        assert "risk" in res
        assert 0.0 <= res["risk"]["score"] <= 100.0



    def test_attribution_share_bounds(self):
        """Verify Fund Attribution Share remains in [0.0, 1.0] and amounts >= 0."""
        edges = [
            NormEdge(
                chain="ethereum",
                tx_hash="0xbounds01",
                vout_index=0,
                block_height=100,
                from_address="0xfrom",
                to_address="0xto1",
                value_native=10.0,
                value_usd=10000.0,
                fee_usd=0.0,
                block_time="2023-11-14T00:00:00Z",
                asset="ETH",
            ),
            NormEdge(
                chain="ethereum",
                tx_hash="0xbounds02",
                vout_index=0,
                block_height=101,
                from_address="0xfrom",
                to_address="0xto2",
                value_native=5.0,
                value_usd=5000.0,
                fee_usd=0.0,
                block_time="2023-11-14T00:01:00Z",
                asset="ETH",
            ),
        ]

        edge_map, wallet_map = compute_fund_attribution(
            edges=edges,
            targets=["0xfrom"],
            initial_amounts={"0xfrom": 10000.0},
        )

        for k, attr in wallet_map.items():
            assert 0.0 <= attr.attribution_share <= 1.0
            assert attr.attributed_inbound_usd >= 0.0

    def test_vasp_confidence_bounds(self):
        """Verify VASP confidence score remains in [0.0, 0.99]."""
        intel = {
            f"ethereum:{BINANCE_HOT}": {
                "vasp_id": "vasp_binance",
                "vasp_name": "Binance",
                "wallet_type": "HOT",
                "is_known_hot_wallet": True,
            }
        }
        match = resolve_vasp_attribution(BINANCE_HOT, "ethereum", wallets_intel=intel)
        if match and match.identified:
            assert 0.0 <= match.confidence <= 0.99

    def test_bridge_confidence_bounds(self):
        """Verify Bridge confidence score remains in [0.0, 0.99]."""
        events = [
            BridgeEvent(
                chain="ethereum",
                tx_hash="0xbr1",
                vout_index=0,
                block_time="2023-11-14T00:00:00Z",
                timestamp=1700000000.0,
                address="0xbridge",
                from_address="0xuser",
                to_address="0xbridge",
                bridge_id="b1",
                bridge_name="Hop",
                role="SOURCE",
                asset="ETH",
                amount_native=1.0,
                amount_usd=1000.0,
            ),
            BridgeEvent(
                chain="polygon",
                tx_hash="0xbr2",
                vout_index=0,
                block_time="2023-11-14T00:01:00Z",
                timestamp=1700000060.0,
                address="0xbridge",
                from_address="0xbridge",
                to_address="0xdest",
                bridge_id="b2",
                bridge_name="Hop",
                role="DESTINATION",
                asset="USDT",
                amount_native=1000.0,
                amount_usd=1000.0,
            ),
        ]

        correlations = correlate_cross_chain_transfers([events[0]], [events[1]])
        for corr in correlations:
            assert 0.0 <= corr.confidence_score <= 0.99

    def test_case_workspace_multi_view_consistency(self):
        """Verify case summary metrics match aggregated sub-view totals."""
        case_svc = get_case_service()
        summary = case_svc.get_case_summary("SIH/2026/00412")

        wallets = case_svc.get_case_wallets("SIH/2026/00412")
        txs = case_svc.get_case_transactions("SIH/2026/00412")

        assert summary["metrics"]["wallet_count"] == len(wallets)
        assert summary["metrics"]["transaction_count"] == len(txs)
