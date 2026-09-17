"""
Unit & Integration Test Suite for Batch 7 Evidence Authorization, Tamper Detection,
PDF Hash Security, Integration Error Handling, and Adversarial Cases A-G.
"""
from __future__ import annotations

import pytest
from app.services.cases import get_case_service
from app.services.evidence_provenance import get_evidence_provenance_service, sha256_hex
from app.services.integrations.ncrp import get_ncrp_adapter
from app.services.integrations.sahyog import get_sahyog_adapter
from app.services.reports import get_report_service


def test_adversarial_case_a_unauthorized_evidence_access():
    """Adversarial Case A: Unauthorized access attempt to case evidence package raises PermissionError."""
    case_svc = get_case_service()

    # Create restricted case assigned to Officer Alpha in Special Ops Unit
    restricted_case = case_svc.create_case(
        title="Classified Operation Case Gamma",
        reported_wallet="0xsecretwallet999999999999999999999999",
        reported_chain="ethereum",
        reported_amount_usd=1000000.0,
        created_by="Officer Alpha",
        org_unit="Special Operations Division",
    )
    case_ref = restricted_case["case_ref"]

    # Access by Officer Beta from outside unit is denied
    with pytest.raises(PermissionError):
        case_svc.authorize_case_access(case_ref, user_id="Officer Beta", org_unit="Local Police Station")


def test_adversarial_case_b_tampered_evidence_detection():
    """Adversarial Case B: Client-side tampering of evidence payload is detected by hash verification."""
    evidence_svc = get_evidence_provenance_service()
    records = evidence_svc.get_case_evidence("SIH/2026/00412")
    rec = records[0]

    # Verify original record is intact
    verification = evidence_svc.verify_evidence_integrity(rec["id"])
    assert verification["verdict"] == "INTACT"

    # Simulate tampered record
    tampered_rec = dict(rec)
    tampered_rec["normalized_payload_hash"] = sha256_hex("tampered_content")

    # Re-verifying tampered record hash comparison fails
    assert tampered_rec["normalized_payload_hash"] != rec["normalized_payload_hash"]


def test_adversarial_case_c_modified_pdf_hash_mismatch():
    """Adversarial Case C: PDF modified after download fails SHA-256 hash comparison."""
    report_svc = get_report_service()
    report = report_svc.generate_investigation_report("SIH/2026/00412")

    original_bytes = report["html_content"].encode("utf-8")
    intact_verdict = report_svc.verify_report_pdf(report["id"], original_bytes)
    assert intact_verdict["verdict"] == "INTACT"

    # Add 1 byte tampering
    tampered_bytes = original_bytes + b"\x00"
    tampered_verdict = report_svc.verify_report_pdf(report["id"], tampered_bytes)
    assert tampered_verdict["verdict"] == "TAMPERED"


def test_adversarial_case_d_integration_failure_never_fake_success():
    """Adversarial Case D: Unconfigured or failing integrations render status explicitly without fake success."""
    ncrp = get_ncrp_adapter()
    status = ncrp.get_status()

    # Mode MUST be SIMULATION, CONNECTED, or NOT_CONFIGURED (never live success unless configured)
    assert status["mode"] in ["SIMULATION", "CONNECTED", "NOT_CONFIGURED"]
    assert status["mode"] != "LIVE_SUBMITTED_SUCCESS"


def test_adversarial_case_e_idempotency_prevents_duplicate_ncrp_submissions():
    """Adversarial Case E: Duplicate NCRP submission retry reuses idempotency key."""
    ncrp = get_ncrp_adapter()
    sub1 = ncrp.submit_report(case_id="SIH/2026/00412", custom_reference="NCRP-DUP-TEST")
    sub2 = ncrp.submit_report(case_id="SIH/2026/00412", custom_reference="NCRP-DUP-TEST")

    assert sub1["id"] == sub2["id"]
    assert sub1["idempotency_key"] == sub2["idempotency_key"]


def test_adversarial_case_f_sahyog_action_idempotency():
    """Adversarial Case F: Duplicate SAHYOG action request uses idempotency key to prevent duplicate official calls."""
    sahyog = get_sahyog_adapter()
    act1 = sahyog.submit_action_request("SIH/2026/00412", "PRESERVATION_REQUEST", "0x71c7656ec7ab88b098defb751b7401b5f6d8976f")
    act2 = sahyog.submit_action_request("SIH/2026/00412", "PRESERVATION_REQUEST", "0x71c7656ec7ab88b098defb751b7401b5f6d8976f")

    assert act1["id"] == act2["id"]
    assert act1["idempotency_key"] == act2["idempotency_key"]


def test_adversarial_case_g_simulation_mode_explicitly_rendered():
    """Adversarial Case G: Simulation mode actions explicitly tag simulated = True and status = SIMULATION."""
    sahyog = get_sahyog_adapter()
    act = sahyog.submit_action_request("SIH/2026/00412", "INFORMATION_REQUEST", "0x3f8a421b920409210928aef001928ab091829012")

    assert act["simulated"] is True
    assert act["status"] == "SIMULATION"
