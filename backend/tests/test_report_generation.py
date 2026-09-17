"""
Unit & Integration Test Suite for Batch 7 Investigation Report Generation,
PDF SHA-256 Hash Integrity, Report Versioning, and Preservation Notices.
"""
from __future__ import annotations

import pytest
from app.services.evidence_provenance import sha256_hex
from app.services.reports import InvestigationReportService, get_report_service


def test_generate_investigation_report():
    """Generates server-side HTML/PDF report and verifies PDF SHA-256 hash calculation."""
    svc = get_report_service()
    report = svc.generate_investigation_report("SIH/2026/00412", custom_notes="Officer note: Subpoena target Binance")

    assert report["id"].startswith("RPT-")
    assert report["case_id"] == "SIH/2026/00412"
    assert report["report_version"].startswith("v1.")
    assert len(report["pdf_hash"]) == 64  # SHA-256 hex length
    assert "Forensic Investigation Report" in report["html_content"]
    assert "Legal & Technical Limitations Notice" in report["html_content"]


def test_report_versioning_increments():
    """Regenerating a report for the same case creates a new version record without overwriting previous ones."""
    svc = get_report_service()
    rep1 = svc.generate_investigation_report("SIH/2026/00412")
    rep2 = svc.generate_investigation_report("SIH/2026/00412")

    assert rep1["id"] != rep2["id"]
    assert rep1["report_version"] != rep2["report_version"]

    reports_list = svc.list_reports("SIH/2026/00412")
    assert len(reports_list) >= 2


def test_verify_report_pdf_hash():
    """Verifies stored PDF SHA-256 integrity hash against uploaded/downloaded PDF byte stream."""
    svc = get_report_service()
    reports = svc.list_reports("SIH/2026/00412")
    rep = reports[0]

    # Verify matching bytes
    pdf_bytes = rep["html_content"].encode("utf-8")
    verification = svc.verify_report_pdf(rep["id"], pdf_bytes)

    assert verification["report_id"] == rep["id"]
    assert verification["verdict"] == "INTACT"

    # Verify tampered bytes produce TAMPERED verdict
    tampered_bytes = pdf_bytes + b"_TAMPERED_BYTE"
    tampered_verification = svc.verify_report_pdf(rep["id"], tampered_bytes)
    assert tampered_verification["verdict"] == "TAMPERED"


def test_generate_preservation_notice():
    """Generates formal Section 91 / BNSS preservation request with legal jurisdiction metadata."""
    svc = get_report_service()
    notice = svc.generate_preservation_notice(
        case_id="SIH/2026/00412",
        recipient_vasp="Coinbase",
        target_address="0x71c7656ec7ab88b098defb751b7401b5f6d8976f",
        legal_jurisdiction="Section 91 CrPC / BNSS India",
    )

    assert notice["case_id"] == "SIH/2026/00412"
    assert notice["recipient_vasp"] == "Coinbase"
    assert "OFFICIAL LEGAL PRESERVATION REQUEST" in notice["notice_text"]
    assert "Section 91 CrPC / BNSS India" in notice["jurisdiction"]
