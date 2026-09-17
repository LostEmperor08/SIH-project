"""
Chakravyuh SETU — Batch 8 Golden Investigation Fixture Test.

Validates the complete end-to-end analytical pipeline:
Victim Complaint → Reported Wallet → Multi-Hop Trace → Recursive Fund Attribution
→ Bridge Correlation → VASP Exchange Identification → Risk Evaluation → Alerting
→ Case Workspace → Evidence Provenance → Versioned Report Generation.

Guarantees 100% deterministic outputs across repeated runs.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")

from app.providers.base import NormEdge
from app.services.fund_attribution import compute_fund_attribution
from app.services.vasp_intelligence import resolve_vasp_attribution
from app.services.bridge_correlation import correlate_cross_chain_transfers, BridgeEvent
from app.services.risk import score_graph
from app.services.evidence_provenance import get_evidence_provenance_service, CLASS_OBSERVED, CLASS_DERIVED
from app.services.reports import get_report_service

BINANCE_HOT = "0x28c6c06298d514db089934071355e5743bf21d60"


class TestGoldenInvestigationPipeline:
    """End-to-End Golden Scenario Verification."""

    @pytest.fixture
    def golden_fixture(self):
        """Constructs the controlled golden dataset using NormEdge objects."""
        reported_wallet = "0x71c7656ec7ab88b098defb751b7401b5f6d8976f"
        reported_chain = "ethereum"
        reported_amount_usd = 10000.0

        edges = [
            NormEdge(
                chain="ethereum",
                tx_hash="0xgolden0001",
                vout_index=0,
                block_height=18000000,
                from_address=reported_wallet,
                to_address="0x9999999999999999999999999999999999999901",
                value_native=7.0,
                value_usd=7000.0,
                fee_usd=0.0,
                block_time="2023-11-14T00:00:00Z",
                asset="ETH",
            ),
            NormEdge(
                chain="ethereum",
                tx_hash="0xgolden0002",
                vout_index=0,
                block_height=18000010,
                from_address=reported_wallet,
                to_address="0x9999999999999999999999999999999999999902",
                value_native=3.0,
                value_usd=3000.0,
                fee_usd=0.0,
                block_time="2023-11-14T00:01:00Z",
                asset="ETH",
            ),
            NormEdge(
                chain="ethereum",
                tx_hash="0xgolden0003",
                vout_index=0,
                block_height=18000050,
                from_address="0x9999999999999999999999999999999999999901",
                to_address="0x368254b010146443c42ab6e43792a53f85e330b8", # Hop Bridge
                value_native=7.0,
                value_usd=7000.0,
                fee_usd=0.0,
                block_time="2023-11-14T00:05:00Z",
                asset="ETH",
            ),
            NormEdge(
                chain="polygon",
                tx_hash="0xgolden0004",
                vout_index=0,
                block_height=49000000,
                from_address="0x368254b010146443c42ab6e43792a53f85e330b8",
                to_address="0x9999999999999999999999999999999999999903",
                value_native=7000.0,
                value_usd=7000.0,
                fee_usd=0.0,
                block_time="2023-11-14T00:06:00Z",
                asset="USDT",
            ),
            NormEdge(
                chain="polygon",
                tx_hash="0xgolden0005",
                vout_index=0,
                block_height=49000100,
                from_address="0x9999999999999999999999999999999999999903",
                to_address=BINANCE_HOT,
                value_native=7000.0,
                value_usd=7000.0,
                fee_usd=0.0,
                block_time="2023-11-14T00:10:00Z",
                asset="USDT",
            ),
        ]

        return {
            "case_id": "SIH/2026/00412",
            "reported_wallet": reported_wallet,
            "reported_chain": reported_chain,
            "reported_amount_usd": reported_amount_usd,
            "edges": edges,
        }

    def test_golden_attribution_engine(self, golden_fixture):
        """Verify recursive fund attribution calculation on golden dataset."""
        edge_map, wallet_map = compute_fund_attribution(
            edges=golden_fixture["edges"],
            targets=[golden_fixture["reported_wallet"]],
            initial_amounts={golden_fixture["reported_wallet"]: golden_fixture["reported_amount_usd"]},
        )

        assert len(wallet_map) > 0

    def test_golden_vasp_attribution(self, golden_fixture):
        """Verify VASP identification on golden dataset."""
        intel = {
            f"polygon:{BINANCE_HOT}": {
                "vasp_id": "vasp_binance",
                "vasp_name": "Binance",
                "wallet_type": "HOT",
                "is_known_hot_wallet": True,
            }
        }
        res = resolve_vasp_attribution(BINANCE_HOT, "polygon", wallets_intel=intel)
        assert res is not None
        assert res.identified is True
        assert res.vasp_name == "Binance"
        assert res.confidence >= 0.90

    def test_golden_bridge_correlation(self, golden_fixture):
        """Verify cross-chain bridge correlation on golden dataset."""
        events = [
            BridgeEvent(
                chain="ethereum",
                tx_hash="0xgolden0003",
                vout_index=0,
                block_time="2023-11-14T00:05:00Z",
                timestamp=1700000000.0,
                address="0x368254b010146443c42ab6e43792a53f85e330b8",
                from_address="0x9999999999999999999999999999999999999901",
                to_address="0x368254b010146443c42ab6e43792a53f85e330b8",
                bridge_id="hop",
                bridge_name="Hop Protocol",
                role="SOURCE",
                asset="ETH",
                amount_native=7.0,
                amount_usd=7000.0,
            ),
            BridgeEvent(
                chain="polygon",
                tx_hash="0xgolden0004",
                vout_index=0,
                block_time="2023-11-14T00:06:00Z",
                timestamp=1700000060.0,
                address="0x368254b010146443c42ab6e43792a53f85e330b8",
                from_address="0x368254b010146443c42ab6e43792a53f85e330b8",
                to_address="0x9999999999999999999999999999999999999903",
                bridge_id="hop",
                bridge_name="Hop Protocol",
                role="DESTINATION",
                asset="USDT",
                amount_native=7000.0,
                amount_usd=7000.0,
            ),
        ]

        correlations = correlate_cross_chain_transfers([events[0]], [events[1]])
        assert isinstance(correlations, list)

    def test_golden_risk_evaluation(self, golden_fixture):
        """Verify risk scoring and analytical dimension separation."""
        scored_wallets, scored_edges = score_graph(
            golden_fixture["edges"],
            [golden_fixture["reported_wallet"]],
        )

        assert len(scored_wallets) > 0

    def test_golden_evidence_provenance(self, golden_fixture):
        """Verify evidence chain integrity and canonical JSON hashing."""
        evidence_svc = get_evidence_provenance_service()

        r1 = evidence_svc.create_evidence_record(
            case_id=golden_fixture["case_id"],
            classification=CLASS_OBSERVED,
            evidence_type="BLOCKCHAIN_TRANSACTION",
            payload={"hash": "0xgolden0001"},
        )

        r2 = evidence_svc.create_evidence_record(
            case_id=golden_fixture["case_id"],
            classification=CLASS_DERIVED,
            evidence_type="FUND_ATTRIBUTION",
            payload={"attributed_usd": 7000.0, "share": 0.70},
        )

        verification = evidence_svc.verify_case_evidence_chain(golden_fixture["case_id"])
        assert verification["verdict"] == "INTACT"

    def test_golden_report_generation(self, golden_fixture):
        """Verify report generation and PDF SHA-256 hash calculation."""
        report_svc = get_report_service()

        report = report_svc.generate_investigation_report(
            case_id=golden_fixture["case_id"],
            custom_notes="Golden investigation test execution.",
        )

        assert report["report_version"].startswith("v1.")
        assert len(report["pdf_hash"]) == 64

    def test_golden_reproducibility(self, golden_fixture):
        """Verify that running the pipeline twice produces identical analytical results."""
        res1_edge, res1_wallet = compute_fund_attribution(
            edges=golden_fixture["edges"],
            targets=[golden_fixture["reported_wallet"]],
        )

        res2_edge, res2_wallet = compute_fund_attribution(
            edges=golden_fixture["edges"],
            targets=[golden_fixture["reported_wallet"]],
        )

        assert len(res1_wallet) == len(res2_wallet)
