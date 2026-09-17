"""
FastAPI Router for Investigator Case Workspace, Money Trail, Recommendations & Timeline (Batch 6).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from ..schemas import (
    CaseCreate,
    CaseNoteCreate,
    CaseNoteResponse,
    CaseResponse,
    CaseStatusUpdate,
    CaseTaskCreate,
    CaseTaskResponse,
    RecommendationItem,
    TimelineItem,
)
from ..services.cases import get_case_service

log = logging.getLogger("chakravyuh.routers.cases")

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/", response_model=list[CaseResponse])
def list_cases(
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List investigation cases."""
    svc = get_case_service()
    return svc.list_cases(status=status, search=search, limit=limit, offset=offset)


@router.post("/", response_model=CaseResponse, status_code=status.HTTP_217_CREATED if hasattr(status, 'HTTP_217_CREATED') else 201)
def create_case(req: CaseCreate):
    """Register a new investigation case."""
    svc = get_case_service()
    return svc.create_case(
        title=req.title,
        reported_wallet=req.reported_wallet,
        reported_chain=req.reported_chain,
        reported_amount_usd=req.reported_amount_usd,
        description=req.description,
        priority=req.priority,
        org_unit=req.org_unit,
    )


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(case_id: str):
    """Retrieve details for a single investigation case."""
    svc = get_case_service()
    try:
        return svc.authorize_case_access(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{case_id}/status", response_model=CaseResponse)
def update_case_status(case_id: str, req: CaseStatusUpdate):
    """Update case status lifecycle (e.g. OPEN -> ACTIVE -> UNDER_REVIEW -> CLOSED)."""
    svc = get_case_service()
    try:
        return svc.update_case_status(case_id, new_status=req.status, note=req.note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/summary")
def get_case_summary(case_id: str):
    """Consolidated case overview metrics, reported wallet summary, and evidence statement."""
    svc = get_case_service()
    try:
        return svc.get_case_summary(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/wallets")
def get_case_wallets(case_id: str):
    """Discovered wallet list with entity roles, attributed funds, risk, relevance, and VASP info."""
    svc = get_case_service()
    try:
        return svc.get_case_wallets(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/transactions")
def get_case_transactions(
    case_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated transaction workspace table with B1-B5 analytical scores."""
    svc = get_case_service()
    try:
        return svc.get_case_transactions(case_id, limit=limit, offset=offset)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/exchanges")
def get_case_exchanges(case_id: str):
    """Identified exchange endpoints, VASP confidence, and step-by-step path flows."""
    svc = get_case_service()
    try:
        return svc.get_case_exchanges(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/cross-chain")
def get_case_cross_chain(case_id: str):
    """Cross-chain bridge transfers and bridge correlation metrics."""
    svc = get_case_service()
    try:
        return svc.get_case_cross_chain(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/recommendations", response_model=list[RecommendationItem])
def get_case_recommendations(case_id: str):
    """Prioritized investigation recommendations with explicit evidence grounds."""
    svc = get_case_service()
    try:
        return svc.get_case_recommendations(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/timeline", response_model=list[TimelineItem])
def get_case_timeline(case_id: str):
    """Chronological audit and alert event log for the investigation."""
    svc = get_case_service()
    try:
        return svc.get_case_timeline(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/notes", response_model=list[CaseNoteResponse])
def get_case_notes(case_id: str):
    """Retrieve investigator notes for case."""
    svc = get_case_service()
    try:
        return svc.get_notes(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{case_id}/notes", response_model=CaseNoteResponse)
def add_case_note(case_id: str, req: CaseNoteCreate):
    """Add structured investigator note to case."""
    svc = get_case_service()
    try:
        return svc.add_note(case_id, text=req.text, is_pinned=req.is_pinned)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{case_id}/tasks", response_model=list[CaseTaskResponse])
def get_case_tasks(case_id: str):
    """Retrieve lightweight tasks for case."""
    svc = get_case_service()
    try:
        return svc.get_tasks(case_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{case_id}/tasks", response_model=CaseTaskResponse)
def create_case_task(case_id: str, req: CaseTaskCreate):
    """Create lightweight investigator task for case."""
    svc = get_case_service()
    try:
        return svc.create_task(
            case_id,
            title=req.title,
            description=req.description,
            assignee=req.assignee,
            priority=req.priority,
            due_at=req.due_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
