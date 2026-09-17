"""
FastAPI Router for Evidence Provenance, Integrity Verification & Package Export (Batch 7).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..schemas import (
    EvidenceRecordCreate,
    EvidenceRecordResponse,
    EvidenceVerificationResponse,
)
from ..services.evidence_provenance import get_evidence_provenance_service

log = logging.getLogger("chakravyuh.routers.evidence")

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/case/{case_id}", response_model=list[EvidenceRecordResponse])
def get_case_evidence(case_id: str):
    """Retrieve all evidence records for a case."""
    svc = get_evidence_provenance_service()
    return svc.get_case_evidence(case_id)


@router.post("/", response_model=EvidenceRecordResponse)
def create_evidence_record(req: EvidenceRecordCreate):
    """Create and seal a new evidence record into the cryptographic chain."""
    svc = get_evidence_provenance_service()
    return svc.create_evidence_record(
        case_id=req.case_id,
        classification=req.classification,
        evidence_type=req.evidence_type,
        payload=req.payload,
        chain=req.chain,
        address=req.address,
        tx_hash=req.tx_hash,
        block_number=req.block_number,
        source_provider=req.source_provider,
        source_endpoint=req.source_endpoint,
    )


@router.get("/{record_id}/verify", response_model=EvidenceVerificationResponse)
def verify_evidence_integrity(record_id: str):
    """Verify SHA-256 content and chain hash integrity for a single evidence record."""
    svc = get_evidence_provenance_service()
    try:
        return svc.verify_evidence_integrity(record_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/case/{case_id}/verify-chain", response_model=EvidenceVerificationResponse)
def verify_case_evidence_chain(case_id: str):
    """Verify the entire evidence hash chain sequence for an investigation case."""
    svc = get_evidence_provenance_service()
    return svc.verify_case_evidence_chain(case_id)


@router.get("/case/{case_id}/export-package")
def export_evidence_package(case_id: str):
    """Export a machine-readable evidence package with manifest.json and per-file SHA-256 hashes."""
    svc = get_evidence_provenance_service()
    return svc.build_evidence_package(case_id)
