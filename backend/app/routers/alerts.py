"""
Alerts Router — GET /alerts, POST /alerts/{id}/acknowledge, POST /alerts/{id}/resolve, WS /alerts/ws (Batch 5).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from ..config import Settings, get_settings
from ..schemas import AlertActionRequest, AlertResponse
from ..security import Officer, require_role
from ..services.alert_engine import BROADCASTER, STATUS_ACKNOWLEDGED, STATUS_DISMISSED, STATUS_RESOLVED
from ..services.supabase_svc import get_supabase

log = logging.getLogger("chakravyuh.api.alerts")
router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    case_id: str = Query(default="SIH/2026/00412"),
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    chain: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    alerts = await sb.get_alerts(
        case_id=case_id,
        status=status_filter,
        severity=severity,
        chain=chain,
        limit=limit,
        offset=offset
    )
    return alerts


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    alert = await sb.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: str,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    res = await sb.update_alert_status(alert_id, STATUS_ACKNOWLEDGED, officer.full_name)
    if not res:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Alert not found or update failed")
    return res


@router.post("/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: str,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    res = await sb.update_alert_status(alert_id, STATUS_RESOLVED, officer.full_name)
    if not res:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Alert not found or update failed")
    return res


@router.post("/{alert_id}/dismiss", response_model=AlertResponse)
async def dismiss_alert(
    alert_id: str,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    res = await sb.update_alert_status(alert_id, STATUS_DISMISSED, officer.full_name)
    if not res:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Alert not found or update failed")
    return res


@router.websocket("/ws")
async def alerts_websocket(websocket: WebSocket):
    """
    WebSocket streaming endpoint for live real-time alert broadcasts.
    """
    await BROADCASTER.connect(websocket)
    try:
        while True:
            # Keepalive ping/pong
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await BROADCASTER.disconnect(websocket)
    except Exception as e:
        log.warning("Alerts WebSocket error: %s", e)
        await BROADCASTER.disconnect(websocket)
