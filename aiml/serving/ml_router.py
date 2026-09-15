"""
FastAPI router — mount into your existing Chakravyuh SETU backend.

    # main.py
    from serving.ml_router import router as ml_router, lifespan_load_models

    app = FastAPI(lifespan=lifespan_load_models)   # or call load_models() in startup
    app.include_router(ml_router)

Every route reuses YOUR existing auth dependency. Replace `require_officer`
below with the Supabase bearer-token verifier you already wrote for /trace —
the placeholder here fails closed, matching the fail-closed posture in your
report, so an unconfigured deployment refuses rather than serving open.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.features.schema import FEATURES, GROUPS
from .inference import get_bundle, load_models, score_from_subgraph, score_wallets

log = logging.getLogger("chakravyuh.ml.api")

router = APIRouter(prefix="/ml", tags=["ml"])

ALLOWED_CHAINS = {"btc", "eth", "polygon", "tron", "bsc"}


# =====================================================================
# Startup
# =====================================================================
@asynccontextmanager
async def lifespan_load_models(app):
    load_models(os.getenv("ARTIFACTS_DIR", "artifacts"))
    yield


# =====================================================================
# Auth — REPLACE with your existing dependency
# =====================================================================
async def require_officer(request: Request):
    """
    Placeholder. Swap for the verifier you already use on /trace.

    Fails closed: with no auth wired up it refuses every request rather
    than defaulting open. An investigation API that serves unauthenticated
    traffic because someone forgot an env var is a breach, not a bug.
    """
    verifier = getattr(request.app.state, "verify_officer", None)
    if verifier is None:
        raise HTTPException(
            503,
            "ML routes are not wired to an auth verifier. Set "
            "app.state.verify_officer to your Supabase bearer-token check.",
        )
    return await verifier(request)


# =====================================================================
# Schemas
# =====================================================================
class EdgeIn(BaseModel):
    from_address: str = Field(min_length=10, max_length=128)
    to_address: str = Field(min_length=10, max_length=128)
    value_usd: float = 0.0
    ts: float | None = None
    block_time: str | None = None
    tx_hash: str = ""


class ScoreRequest(BaseModel):
    chain: str
    addresses: list[str] = Field(min_length=1, max_length=200)
    edges: list[EdgeIn] = Field(min_length=1, max_length=50_000)
    sanctioned: list[str] = []
    mixers: list[str] = []
    exchanges: list[str] = []
    darknet: list[str] = []
    bridges: list[str] = []
    explain: bool = True

    @field_validator("chain")
    @classmethod
    def _chain_ok(cls, v: str) -> str:
        if v not in ALLOWED_CHAINS:
            raise ValueError(f"chain must be one of {sorted(ALLOWED_CHAINS)}")
        return v


class FeatureScoreRequest(BaseModel):
    """For when your caller has already computed features."""
    rows: list[dict] = Field(min_length=1, max_length=500)
    explain: bool = True


class FeedbackRequest(BaseModel):
    address: str
    chain: str
    verdict: Literal["confirmed_fraud", "false_positive", "inconclusive"]
    typology: str | None = None
    vasp_name: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


# =====================================================================
# Routes
# =====================================================================
@router.get("/health")
async def ml_health():
    """Public — deliberately exposes no model internals."""
    b = get_bundle()
    return {"ok": True, "models_ready": b.ready,
            "loaded": b.status()["loaded"]}


@router.get("/models", dependencies=[Depends(require_officer)])
async def model_info():
    """Versions, training dates and metrics — the audit answer."""
    return get_bundle().status() | {"manifests": get_bundle().manifests}


@router.get("/features", dependencies=[Depends(require_officer)])
async def feature_catalogue():
    """What the models look at, in plain language — for the officer's UI."""
    return {
        "count": len(FEATURES),
        "groups": GROUPS,
        "features": [{"name": f.name, "group": f.group,
                      "description": f.description, "signal": f.signal}
                     for f in FEATURES],
    }


@router.post("/score", dependencies=[Depends(require_officer)])
async def score(req: ScoreRequest):
    """
    Score wallets from a traced subgraph.

    Feed this the edges your /trace endpoint already fetched — no second
    call to Blockstream or Blockscout.
    """
    b = get_bundle()
    if not b.ready:
        raise HTTPException(503, "no trained models loaded — run src/train.py first")
    try:
        results = score_from_subgraph(
            [e.model_dump() for e in req.edges],
            req.addresses,
            sanctioned=set(req.sanctioned), mixers=set(req.mixers),
            exchanges=set(req.exchanges), darknet=set(req.darknet),
            bridges=set(req.bridges), explain=req.explain,
        )
    except Exception as e:
        log.exception("scoring failed")
        raise HTTPException(400, f"scoring failed: {e}")

    return {
        "chain": req.chain,
        "scored": len(results),
        "model_versions": b.status()["versions"],
        "results": results,
    }


@router.post("/score-features", dependencies=[Depends(require_officer)])
async def score_features(req: FeatureScoreRequest):
    import pandas as pd
    b = get_bundle()
    if not b.ready:
        raise HTTPException(503, "no trained models loaded")
    df = pd.DataFrame(req.rows).fillna(0.0)
    from src.features.schema import FEATURE_NAMES
    for c in FEATURE_NAMES:
        if c not in df.columns:
            df[c] = 0.0
    return {"results": score_wallets(df, explain=req.explain)}


@router.post("/triage", dependencies=[Depends(require_officer)])
async def triage(req: ScoreRequest):
    """
    Same as /score but returns only what a case-triage screen needs —
    roughly a tenth of the payload, which matters when an officer is on
    a phone on a 4G connection.
    """
    b = get_bundle()
    if not b.ready:
        raise HTTPException(503, "no trained models loaded")
    full = score_from_subgraph(
        [e.model_dump() for e in req.edges], req.addresses,
        sanctioned=set(req.sanctioned), mixers=set(req.mixers),
        exchanges=set(req.exchanges), darknet=set(req.darknet),
        bridges=set(req.bridges), explain=False,
    )
    slim = [{
        "address": r["address"],
        "risk_score": r["risk_score"],
        "risk_band": r["risk_band"],
        "vasp": (r.get("vasp_attribution") or {}).get("type"),
        "hops_to_exchange": r["hops_to_exchange"],
        "top_typology": (r["typologies"][0]["typology"] if r["typologies"] else None),
        "action": (r["recommended_actions"][0] if r["recommended_actions"] else None),
    } for r in full]
    slim.sort(key=lambda r: -r["risk_score"])
    return {"chain": req.chain, "results": slim}


@router.post("/feedback", dependencies=[Depends(require_officer)])
async def feedback(req: FeedbackRequest, request: Request):
    """
    Analyst ground truth — this is how the model improves after deployment.

    Written to Supabase `ml_feedback`. The next training run weights these
    labels above every weak label, which is the whole point: the system
    learns from the officers using it rather than staying frozen at
    whatever the heuristics guessed on day one.
    """
    sb = getattr(request.app.state, "supabase", None)
    if sb is None:
        raise HTTPException(503, "supabase client not attached to app.state")
    officer = getattr(request.state, "officer_id", None)
    try:
        sb.table("ml_feedback").insert({
            "address": req.address, "chain": req.chain,
            "verdict": req.verdict, "typology": req.typology,
            "vasp_name": req.vasp_name, "notes": req.notes,
            "officer_id": officer,
        }).execute()
    except Exception as e:
        raise HTTPException(500, f"could not record feedback: {e}")
    return {"ok": True, "recorded": req.address}


@router.post("/reload", dependencies=[Depends(require_officer)])
async def reload_models(request: Request):
    """Hot-swap to newly trained artifacts without restarting the API."""
    if getattr(request.state, "officer_role", None) != "admin":
        raise HTTPException(403, "admin role required")
    b = load_models(os.getenv("ARTIFACTS_DIR", "artifacts"))
    return {"ok": True, **b.status()}
