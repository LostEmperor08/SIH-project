"""
Unit & Integration Test Suite for Batch 7 Government Integrations (NCRP & SAHYOG Adapters),
Simulation Modes, Payload Contracts, and Idempotency.
"""
from __future__ import annotations

import pytest
from app.services.integrations.ncrp import NCRPAdapter, get_ncrp_adapter
from app.services.integrations.sahyog import SAHYOGAdapter, get_sahyog_adapter


def test_ncrp_adapter_status_and_simulation():
    """NCRP adapter status correctly renders SIMULATION mode."""
    adapter = get_ncrp_adapter()
    status = adapter.get_status()

    assert status["integration"] == "NCRP"
    assert status["mode"] in ["SIMULATION", "CONNECTED", "NOT_CONFIGURED"]
    assert status["active"] is True
    assert "Simulation Mode Active" in status["description"]


def test_ncrp_submit_report_simulation_and_idempotency():
    """Submits report to NCRP adapter in simulation mode and verifies idempotency deduplication."""
    adapter = get_ncrp_adapter()
    res1 = adapter.submit_report(case_id="SIH/2026/00412", custom_reference="NCRP-REF-001")

    assert res1["id"].startswith("ncrp-")
    assert res1["integration"] == "NCRP"
    assert res1["status"] == "SIMULATION"
    assert res1["simulated"] is True
    assert res1["external_reference"] == "NCRP-REF-001"
    assert len(res1["idempotency_key"]) == 32

    # Duplicate submission with identical parameters MUST return the exact same action record
    res2 = adapter.submit_report(case_id="SIH/2026/00412", custom_reference="NCRP-REF-001")
    assert res1["id"] == res2["id"]
    assert res1["idempotency_key"] == res2["idempotency_key"]


def test_sahyog_adapter_status_and_action_request():
    """SAHYOG adapter status renders SIMULATION mode and executes action request."""
    adapter = get_sahyog_adapter()
    status = adapter.get_status()

    assert status["integration"] == "SAHYOG"
    assert status["mode"] in ["SIMULATION", "CONNECTED", "NOT_CONFIGURED"]

    action_res = adapter.submit_action_request(
        case_id="SIH/2026/00412",
        action_type="PRESERVATION_REQUEST",
        target_wallet="0x71c7656ec7ab88b098defb751b7401b5f6d8976f",
        target_vasp="Coinbase",
    )

    assert action_res["id"].startswith("sahyog-")
    assert action_res["integration"] == "SAHYOG"
    assert action_res["action_type"] == "PRESERVATION_REQUEST"
    assert action_res["status"] == "SIMULATION"
    assert action_res["simulated"] is True
    assert len(action_res["idempotency_key"]) == 32
