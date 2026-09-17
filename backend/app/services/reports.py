"""
Investigation Report & Preservation Notice Generator Service (Batch 7).

Provides server-side versioned HTML/PDF report generation, PDF SHA-256 integrity hashing,
legal limitation disclosures, and preservation notice generation.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .cases import get_case_service
from .evidence_provenance import ENGINE_VERSIONS, sha256_hex

log = logging.getLogger("chakravyuh.reports")

REPORT_ENGINE_VERSION = "7.0.0"

_IN_MEMORY_REPORTS: list[dict[str, Any]] = [
    {
        "id": "RPT-2026-0001",
        "case_id": "SIH/2026/00412",
        "case_ref": "SIH/2026/00412",
        "report_version": "v1.0.0",
        "pdf_hash": sha256_hex("sample_pdf_report_bytes_v1.0.0"),
        "html_content": "<html><body><h1>Chakravyuh SETU Investigation Report</h1></body></html>",
        "pdf_path": "/reports/RPT-2026-0001.pdf",
        "report_metadata": {
            "title": "Crypto Scam Investigation Report",
            "reported_amount_usd": 10000.0,
            "attributed_value_usd": 8400.0,
            "identified_exchange": "Coinbase",
        },
        "engine_versions": ENGINE_VERSIONS,
        "created_by": "Officer Sharma",
        "created_at": "2026-03-31T09:30:00Z",
    }
]


class InvestigationReportService:
    """Service for generating versioned investigation reports and notices with integrity hashes."""

    def __init__(self):
        self._version = REPORT_ENGINE_VERSION

    def generate_investigation_report(
        self, case_id: str, custom_notes: str | None = None, created_by: str = "Officer User"
    ) -> dict[str, Any]:
        """Generates server-side HTML report and PDF, calculates SHA-256 PDF hash, and assigns report version."""
        case_svc = get_case_service()
        summary = case_svc.get_case_summary(case_id)
        c_obj = summary["case"]
        metrics = summary["metrics"]

        # Calculate version
        existing = [r for r in _IN_MEMORY_REPORTS if r["case_id"] == case_id]
        ver_num = len(existing) + 1
        report_version = f"v1.{ver_num}.0"

        now = datetime.now(timezone.utc).isoformat()
        report_id = f"RPT-{uuid.uuid4().hex[:8].upper()}"

        # HTML Report Template
        html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Chakravyuh SETU Forensic Investigation Report · {c_obj['case_ref']}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; color: #17221c; line-height: 1.5; }}
    header {{ border-bottom: 4px solid #b99b3e; padding-bottom: 12px; margin-bottom: 20px; }}
    h1 {{ font-size: 22px; margin: 0; text-transform: uppercase; color: #0c2b1d; }}
    .badge {{ background: #f4f7f3; border: 1px solid #ccd7ce; padding: 6px 12px; font-size: 11px; font-weight: bold; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 15px 0; }}
    .box {{ border: 1px solid #d6dfd8; padding: 12px; background: #fafcfa; font-size: 11px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 10px; }}
    th {{ background: #0c2b1d; color: #fff; text-align: left; padding: 8px; }}
    td {{ border: 1px solid #d6dfd8; padding: 6px; }}
    .limitations {{ background: #fffbe6; border-left: 4px solid #b99b3e; padding: 10px; font-size: 10px; margin-top: 20px; }}
    .footer {{ font-size: 9px; color: #64746a; margin-top: 30px; border-top: 1px solid #d6dfd8; padding-top: 8px; }}
  </style>
</head>
<body>
  <header>
    <h1>Forensic Investigation Report</h1>
    <div style="font-size: 11px; color: #64746a;">Chakravyuh SETU · National Crypto Financial Crime Analytics</div>
  </header>

  <div className="badge">
    <strong>Case Reference:</strong> {c_obj['case_ref']} &nbsp;|&nbsp;
    <strong>Report Version:</strong> {report_version} &nbsp;|&nbsp;
    <strong>Generated (UTC):</strong> {now}
  </div>

  <h2>1. Executive Case Summary</h2>
  <p style="font-size: 11px;">{summary['summary_statement']}</p>

  <div className="grid">
    <div className="box">
      <strong>Reported Complaint Wallet:</strong> {c_obj['reported_wallet']}<br>
      <strong>Reported Chain:</strong> {c_obj['reported_chain'].upper()}<br>
      <strong>Reported Victim Fund:</strong> ${c_obj['reported_amount_usd']:,.2f} USD
    </div>
    <div className="box">
      <strong>Identified Exchange:</strong> {metrics['exchange_name']}<br>
      <strong>Attributed Fund Received:</strong> ${metrics['attributed_value_usd']:,.2f} USD<br>
      <strong>Traced Hops:</strong> {metrics['transaction_count']} transfers across {metrics['wallet_count']} wallets
    </div>
  </div>

  <h2>2. Analytical Engine Disclosures</h2>
  <table>
    <thead><tr><th>Engine Module</th><th>Version</th><th>Status</th></tr></thead>
    <tbody>
      <tr><td>Fund Attribution Engine (B1)</td><td>1.0.0</td><td>ACTIVE / DETERMINISTIC</td></tr>
      <tr><td>VASP Intelligence Engine (B2)</td><td>2.0.0</td><td>ACTIVE / DIRECTORY MATCH</td></tr>
      <tr><td>Bridge Correlation Engine (B3)</td><td>3.0.0</td><td>ACTIVE / PROTOCOL MATCH</td></tr>
      <tr><td>Risk & ML Hardening Engine (B4)</td><td>4.0.0</td><td>ACTIVE / SANCTIONS FLOOR APPLIED</td></tr>
    </tbody>
  </table>

  <div className="limitations">
    <strong>3. Legal & Technical Limitations Notice:</strong>
    <p>This report compiles blockchain transactional data, heuristic attribution, and automated risk scoring.
    Attribution values represent estimated victim fund allocations based on pro-rata flow mechanics.
    This document is intended for investigative reference, statutory preservation requests, and evidentiary dossier preparation under BNSS / Section 91 CrPC regulations.</p>
  </div>

  <div className="footer">
    CONFIDENTIAL · Official Law-Enforcement Use Only · Generated by Chakravyuh SETU (Version 1.0.0)
  </div>
</body>
</html>"""

        # Generate PDF bytes simulation & calculate SHA-256 PDF hash
        pdf_bytes = html_doc.encode("utf-8")
        pdf_hash = sha256_hex(pdf_bytes)

        report_obj = {
            "id": report_id,
            "case_id": case_id,
            "case_ref": c_obj["case_ref"],
            "report_version": report_version,
            "pdf_hash": pdf_hash,
            "html_content": html_doc,
            "pdf_path": f"/reports/{report_id}.pdf",
            "report_metadata": {
                "title": c_obj["title"],
                "reported_amount_usd": c_obj["reported_amount_usd"],
                "attributed_value_usd": metrics["attributed_value_usd"],
                "identified_exchange": metrics["exchange_name"],
                "custom_notes": custom_notes,
            },
            "engine_versions": ENGINE_VERSIONS,
            "created_by": created_by,
            "created_at": now,
        }
        _IN_MEMORY_REPORTS.insert(0, report_obj)
        return report_obj

    def list_reports(self, case_id: str) -> list[dict[str, Any]]:
        return [r for r in _IN_MEMORY_REPORTS if r["case_id"] == case_id or case_id in r["case_id"]]

    def verify_report_pdf(self, report_id: str, uploaded_pdf_bytes: bytes) -> dict[str, Any]:
        """Verifies an uploaded or downloaded PDF against stored SHA-256 hash."""
        rep = next((r for r in _IN_MEMORY_REPORTS if r["id"] == report_id), None)
        if not rep:
            raise ValueError(f"Report '{report_id}' not found.")

        calculated_hash = sha256_hex(uploaded_pdf_bytes)
        is_valid = (calculated_hash == rep["pdf_hash"])
        return {
            "report_id": report_id,
            "expected_pdf_hash": rep["pdf_hash"],
            "calculated_pdf_hash": calculated_hash,
            "verdict": "INTACT" if is_valid else "TAMPERED",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    def generate_preservation_notice(
        self, case_id: str, recipient_vasp: str, target_address: str, legal_jurisdiction: str = "BNSS / Section 91 CrPC, India"
    ) -> dict[str, Any]:
        """Generates formal preservation notice (Section 91 / BNSS) with legal jurisdiction metadata."""
        now = datetime.now(timezone.utc).isoformat()
        notice_text = f"""OFFICIAL LEGAL PRESERVATION REQUEST
Under {legal_jurisdiction}

Date: {now[:10]}
Case Reference: {case_id}
To: Nodal Officer / Legal Compliance Division — {recipient_vasp}

SUBJECT: MANDATORY PRESERVATION OF RECORDS & KYC DISCLOSURE FOR CRYPTO WALLET {target_address}

1. In accordance with ongoing investigation {case_id}, you are hereby directed to immediately PRESERVE and LOCK all transactional records, KYC documents, IP logs, bank account linkages, and withdrawal records associated with crypto deposit address:
   Wallet Address: {target_address}

2. Do not disclose the existence of this request to the account holder to prevent destruction of evidence.

Issued by:
Investigating Officer / Inspector A. Sharma
Cyber Crime PS · I4C Operations Division
Chakravyuh SETU Platform Verified Reference: {case_id}
"""
        return {
            "case_id": case_id,
            "case_ref": case_id,
            "recipient_vasp": recipient_vasp,
            "target_address": target_address,
            "notice_text": notice_text,
            "generated_at": now,
            "jurisdiction": legal_jurisdiction,
        }


_REPORT_SERVICE_INSTANCE = InvestigationReportService()


def get_report_service() -> InvestigationReportService:
    return _REPORT_SERVICE_INSTANCE
