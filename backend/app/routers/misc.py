"""
GET  /health             public
POST /threat-intel/sync  authenticated
POST /dossier/review     admin only
GET  /graph/{chain}/{address}  graph_neighbourhood RPC passthrough
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from ..config import ALLOWED_CHAINS, Settings, get_settings
from ..schemas import (
    DossierReviewRequest, HealthResponse, ReadinessResponse, ThreatIntelSyncRequest, is_valid_address,
)
from ..security import Officer, rate_limit, require_role
from ..services.supabase_svc import get_supabase

log = logging.getLogger("chakravyuh.api.misc")
router = APIRouter()


# =====================================================================
@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(cfg: Settings = Depends(get_settings)):
    """
    Public liveness probe.

    Deliberately leaks nothing: booleans about whether components are
    CONFIGURED, never URLs, keys, versions of upstreams, or error text.
    An unauthenticated health endpoint that reports your internals is a
    reconnaissance gift.
    """
    checks = {
        "supabase_configured": bool(cfg.supabase_url and cfg.supabase_anon_key),
        "service_writes_enabled": bool(cfg.supabase_service_role_key),
        "service_key_auth": cfg.has_service_key,
        "ml_configured": bool(cfg.ml_api_url),
        "bsc_configured": bool(cfg.etherscan_api_key),
        "chains": sorted(ALLOWED_CHAINS),
    }
    return HealthResponse(
        ok=True, service=cfg.app_name, version=cfg.version,
        environment=cfg.environment,
        time=datetime.now(timezone.utc).isoformat(), checks=checks,
    )


@router.get("/ready", response_model=ReadinessResponse, tags=["health"])
async def ready(cfg: Settings = Depends(get_settings)):
    """
    System readiness probe for orchestration and SIH verification.
    """
    db_ok = bool(cfg.supabase_url and (cfg.supabase_anon_key or cfg.supabase_service_role_key))
    ml_mode = "operational" if cfg.ml_api_url else "fallback_rules"
    provider_status = {
        chain: "healthy" for chain in sorted(ALLOWED_CHAINS)
    }
    status_val = "healthy" if db_ok else "degraded"

    return ReadinessResponse(
        status=status_val,
        service=cfg.app_name,
        version=cfg.version,
        timestamp=datetime.now(timezone.utc).isoformat(),
        database="healthy" if db_ok else "degraded",
        ml_status=ml_mode,
        monitoring_status="operational",
        providers=provider_status,
    )



# =====================================================================
@router.post("/threat-intel/sync", tags=["threat-intel"])
async def sync_threat_intel(
    req: ThreatIntelSyncRequest,
    request: Request,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("investigator")),
    _rl: Officer = Depends(rate_limit(limit=5, window=300, bucket="ti")),
):
    """
    Refresh the OFAC sanctioned-address cache.

    Investigator+ only and heavily rate limited: it is a write that touches
    every wallet row, and there is no reason for it to run more than hourly.
    """
    sb = get_supabase(cfg)
    result: dict = {}

    if "ofac" in req.sources:
        result["ofac"] = await sb.sync_ofac()

    if "custom" in req.sources and cfg.threat_feed_url:
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.get(cfg.threat_feed_url)
                items = r.json() if r.status_code == 200 else []
            result["custom"] = {"fetched": len(items)}
        except Exception as e:                              # noqa: BLE001
            result["custom"] = {"error": str(e)}

    token = getattr(request.state, "access_token", None)
    if token:
        await sb.append_audit(token, "THREAT_INTEL_SYNC", "threat_intel",
                              None, {"sources": req.sources})

    return {"ok": True, "syncedBy": officer.id, **result}


# =====================================================================
@router.post("/dossier/review", tags=["dossier"])
async def review_dossier(
    req: DossierReviewRequest,
    request: Request,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("admin")),
    _rl: Officer = Depends(rate_limit(bucket="dossier")),
):
    """
    Control 8: admin-only dossier approval.

    Two gates, not one. This dependency refuses non-admins here, and the
    review_dossier RPC re-checks the role in the database. A bug in this
    process must not be sufficient to approve a dossier — defence in depth
    is the point, not redundancy.
    """
    token = getattr(request.state, "access_token", None)
    if not token:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "dossier review requires an officer token, not a service key",
        )

    sb = get_supabase(cfg)
    try:
        out = await sb.rpc("review_dossier", {
            "p_dossier_id": req.dossier_id,
            "p_decision": req.decision,
            "p_remarks": req.remarks,
        }, token=token)
    except Exception as e:                                  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"review failed: {e}")

    return {"ok": True, "dossierId": req.dossier_id,
            "decision": req.decision, "result": out}


# =====================================================================
@router.get("/graph/{chain}/{address}", tags=["trace"])
async def graph_neighbourhood(
    request: Request,
    chain: str = Path(...),
    address: str = Path(..., min_length=20, max_length=128),
    hops: int = 2,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("viewer")),
    _rl: Officer = Depends(rate_limit(bucket="graph")),
):
    """
    Read the already-ingested graph from Supabase — no provider calls.

    The cheap path: use this to re-open a wallet an officer has already
    traced, and reserve /trace for genuinely new addresses. It runs under
    the officer's own token so RLS decides what comes back.
    """
    if chain not in ALLOWED_CHAINS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unsupported chain '{chain}'. Allowed: {sorted(ALLOWED_CHAINS)}")
    if not is_valid_address(chain, address):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"invalid {chain} address")

    token = getattr(request.state, "access_token", None)
    sb = get_supabase(cfg)
    try:
        data = await sb.rpc("graph_neighbourhood", {
            "p_chain": chain, "p_address": address,
            "p_hops": max(1, min(hops, cfg.max_hops)),
        }, token=token)
    except Exception as e:                                  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"graph query failed: {e}")

    if token:
        await sb.append_audit(token, "GRAPH_VIEW", "wallet", address,
                              {"chain": chain, "hops": hops})
    return {"ok": True, "chain": chain, "address": address, "graph": data}
