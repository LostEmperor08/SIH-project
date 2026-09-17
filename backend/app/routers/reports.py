"""
FastAPI Router for Investigation Reports, PDF Download, Integrity Verification & Preservation Notices (Batch 7).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from ..schemas import (
    NoticeGenerateRequest,
    NoticeResponse,
    ReportGenerateRequest,
    ReportResponse,
)
from ..services.reports import get_report_service

log = logging.getLogger("chakravyuh.routers.reports")

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate/{case_id}", response_model=ReportResponse)
def generate_investigation_report(case_id: str, req: ReportGenerateRequest | None = None):
    """Generates server-side versioned HTML/PDF report with SHA-256 PDF integrity hash."""
    svc = get_report_service()
    notes = req.custom_notes if req else None
    return svc.generate_investigation_report(case_id, custom_notes=notes)


@router.get("/case/{case_id}", response_model=list[ReportResponse])
def list_case_reports(case_id: str):
    """List all generated report versions for an investigation case."""
    svc = get_report_service()
    return svc.list_reports(case_id)


@router.get("/{report_id}/pdf")
def download_report_pdf(report_id: str):
    """Download report PDF byte stream with SHA-256 header integrity metadata."""
    svc = get_report_service()
    reports = [r for r in svc.list_reports("SIH/2026/00412") if r["id"] == report_id]
    if not reports:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found.")
    rep = reports[0]

    content = rep["html_content"].encode("utf-8")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={report_id}.pdf",
            "X-Report-PDF-SHA256": rep["pdf_hash"],
        },
    )


@router.get("/{report_id}/verify")
def verify_report_pdf(report_id: str):
    """Verify stored SHA-256 integrity hash for a generated report."""
    svc = get_report_service()
    reports = [r for r in svc.list_reports("SIH/2026/00412") if r["id"] == report_id]
    if not reports:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found.")
    rep = reports[0]
    return svc.verify_report_pdf(report_id, rep["html_content"].encode("utf-8"))


@router.post("/notice/{case_id}", response_model=NoticeResponse)
def generate_preservation_notice(case_id: str, req: NoticeGenerateRequest):
    """Generate formal Section 91 / BNSS preservation notice with legal jurisdiction template metadata."""
    svc = get_report_service()
    return svc.generate_preservation_notice(
        case_id=case_id,
        recipient_vasp=req.recipient_vasp,
        target_address=req.target_address,
        legal_jurisdiction=req.legal_jurisdiction,
    )
