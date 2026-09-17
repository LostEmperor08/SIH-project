"""
FastAPI Router for Government Integrations (NCRP & SAHYOG Outbound Adapters — Batch 7).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from ..schemas import (
    IntegrationActionResponse,
    IntegrationStatusResponse,
    NCRPSubmitRequest,
    SahyogSubmitRequest,
)
from ..services.integrations.ncrp import get_ncrp_adapter
from ..services.integrations.sahyog import get_sahyog_adapter

log = logging.getLogger("chakravyuh.routers.integrations")

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status", response_model=IntegrationStatusResponse)
def get_integration_status():
    """Retrieve operational status for NCRP and SAHYOG integration adapters."""
    ncrp = get_ncrp_adapter().get_status()
    sahyog = get_sahyog_adapter().get_status()

    return {
        "ncrp_mode": ncrp["mode"],
        "sahyog_mode": sahyog["mode"],
        "ncrp_active": ncrp["active"],
        "sahyog_active": sahyog["active"],
        "description": "Government Integrations Layer — Simulation Mode Active (No live API calls executed without explicit government sandbox configuration).",
    }


@router.post("/ncrp/submit", response_model=IntegrationActionResponse)
def submit_ncrp_report(req: NCRPSubmitRequest):
    """Submits case evidence package to NCRP adapter (uses idempotency key)."""
    ncrp = get_ncrp_adapter()
    return ncrp.submit_report(
        case_id=req.case_id,
        submit_report=req.submit_report,
        custom_reference=req.custom_reference,
    )


@router.post("/sahyog/action", response_model=IntegrationActionResponse)
def submit_sahyog_action(req: SahyogSubmitRequest):
    """Submits inter-state law enforcement action request to SAHYOG adapter (uses idempotency key)."""
    sahyog = get_sahyog_adapter()
    return sahyog.submit_action_request(
        case_id=req.case_id,
        action_type=req.action_type,
        target_wallet=req.target_wallet,
        target_vasp=req.target_vasp,
    )
