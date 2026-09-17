"""
Monitored Wallets Router — CRUD for monitored targets & surveillance status (Batch 5).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import Settings, get_settings
from ..schemas import MonitoredWalletCreate, MonitoredWalletResponse
from ..security import Officer, require_role
from ..services.monitoring import get_monitoring_service
from ..services.supabase_svc import get_supabase

log = logging.getLogger("chakravyuh.api.monitoring")
router = APIRouter(prefix="/monitored-wallets", tags=["monitoring"])


@router.get("", response_model=list[MonitoredWalletResponse])
async def list_monitored_wallets(
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    wallets = await sb.get_active_monitored_wallets()
    return wallets


@router.post("", response_model=MonitoredWalletResponse, status_code=status.HTTP_201_CREATED)
async def create_monitored_wallet(
    req: MonitoredWalletCreate,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    data = req.model_dump()
    data["created_by"] = officer.full_name
    res = await sb.create_monitored_wallet(data)
    if not res:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Failed to create monitored wallet or already exists")
    return res


@router.delete("/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitored_wallet(
    wallet_id: str,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    sb = get_supabase(cfg)
    ok = await sb.delete_monitored_wallet(wallet_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Monitored wallet not found")
    return None


@router.get("/status")
async def monitoring_status(
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
):
    svc = get_monitoring_service(cfg)
    return svc.status()
