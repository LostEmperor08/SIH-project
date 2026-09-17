"""
Unit & Integration Test Suite for Batch 6 Investigator Case Workspace, Summary,
Money Trail, Workspaces (Wallets, Transactions, Exchanges, Cross-Chain), Recommendations, Notes & Tasks.
"""
from __future__ import annotations

import pytest
from app.services.cases import (
    CaseWorkspaceService,
    get_case_service,
    STATUS_ACTIVE,
    STATUS_OPEN,
    STATUS_UNDER_REVIEW,
)


def test_case_service_initialization():
    """CaseWorkspaceService initializes cleanly."""
    svc = get_case_service()
    cases = svc.list_cases()
    assert len(cases) >= 1
    assert cases[0]["case_ref"] == "SIH/2026/00412"


def test_case_creation_and_retrieval():
    """Creates a new investigation case and retrieves it."""
    svc = get_case_service()
    new_case = svc.create_case(
        title="Phishing Scam Investigation Case B",
        reported_wallet="0x1234567890abcdef1234567890abcdef12345678",
        reported_chain="polygon",
        reported_amount_usd=15000.0,
        description="Victim lost 15000 USDC via malicious approve call.",
        priority="URGENT",
    )
    assert new_case["id"] is not None
    assert new_case["case_ref"].startswith("SIH/2026/")

    # Retrieve by case_ref
    fetched = svc.get_case_data(new_case["case_ref"])
    assert fetched is not None
    assert fetched["reported_amount_usd"] == 15000.0
    assert fetched["priority"] == "URGENT"


def test_case_status_transition():
    """Tests case status lifecycle transitions (ACTIVE -> UNDER_REVIEW)."""
    svc = get_case_service()
    updated = svc.update_case_status(
        case_id="SIH/2026/00412",
        new_status="UNDER_REVIEW",
        note="Reviewing Section 91 preservation response from exchange.",
        updated_by="Officer Sharma",
    )
    assert updated["status"] == "UNDER_REVIEW"

    # Timeline event should be recorded
    timeline = svc.get_case_timeline("SIH/2026/00412")
    assert any("STATUS_CHANGED" in t["event_type"] for t in timeline)


def test_case_summary_aggregation():
    """Tests case summary metrics aggregation and evidence summary statement."""
    svc = get_case_service()
    summary = svc.get_case_summary("SIH/2026/00412")
    assert "metrics" in summary
    assert "summary_statement" in summary
    assert summary["metrics"]["reported_amount_usd"] == 10000.0
    assert summary["metrics"]["attributed_value_usd"] > 0
    assert "Reported funds" in summary["summary_statement"]


def test_case_workspaces_data_extraction():
    """Tests wallets, transactions, exchanges, and cross-chain workspaces data."""
    svc = get_case_service()
    wallets = svc.get_case_wallets("SIH/2026/00412")
    txs = svc.get_case_transactions("SIH/2026/00412")
    exchanges = svc.get_case_exchanges("SIH/2026/00412")
    cross_chain = svc.get_case_cross_chain("SIH/2026/00412")

    assert len(wallets) >= 3
    assert len(txs) >= 2
    assert len(exchanges) >= 1
    assert len(cross_chain) >= 1

    # Check exchange structure
    ex = exchanges[0]
    assert ex["exchange_name"] == "Coinbase"
    assert ex["vasp_confidence"] == 0.98
    assert len(ex["evidence"]) > 0
    assert len(ex["path"]) >= 2


def test_case_recommendations_generation():
    """Tests generation of evidence-grounded recommendations."""
    svc = get_case_service()
    recs = svc.get_case_recommendations("SIH/2026/00412")
    assert len(recs) >= 1
    rec1 = recs[0]
    assert rec1["priority"] in ["HIGH", "MEDIUM", "LOW", "INFO"]
    assert len(rec1["basis"]) >= 1
    assert "Section 91 Notice" in rec1["title"] or "Coinbase" in rec1["title"]


def test_case_notes_and_tasks():
    """Tests investigator notes and tasks creation and listing."""
    svc = get_case_service()
    note = svc.add_note("SIH/2026/00412", text="Added subpoena tracking reference #SUB-9912.", author_name="Officer Verma")
    assert note["id"] is not None
    assert note["text"] == "Added subpoena tracking reference #SUB-9912."

    task = svc.create_task("SIH/2026/00412", title="Verify destination wallet KYC", priority="HIGH", assignee="Officer Verma")
    assert task["id"] is not None
    assert task["title"] == "Verify destination wallet KYC"
    assert task["priority"] == "HIGH"
