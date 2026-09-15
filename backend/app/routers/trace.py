"""
POST /trace — the authenticated live blockchain trace.

The endpoint the whole platform exists for. No mock path: if the providers
return nothing, this returns 404 with the provider errors attached. It never
substitutes placeholder edges.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import Settings, get_settings
from ..schemas import TraceRequest, TraceResponse
from ..security import Officer, rate_limit, require_role
from ..services.supabase_svc import get_supabase
from ..services.trace import build_graph, trace_multi_hop

log = logging.getLogger("chakravyuh.api.trace")
router = APIRouter(tags=["trace"])


@router.post("/trace", response_model=TraceResponse)
async def trace(
    req: TraceRequest,
    request: Request,
    cfg: Settings = Depends(get_settings),
    officer: Officer = Depends(require_role("analyst")),
    _rl: Officer = Depends(rate_limit(bucket="trace")),
):
    t0 = time.perf_counter()
    sb = get_supabase(cfg)

    # Control 9: audit the intent before doing the work, so an attempt that
    # later fails or times out still leaves a record that it was made.
    token = getattr(request.state, "access_token", None)
    if token:
        await sb.append_audit(
            token, "TRACE_REQUEST", "wallet",
            req.targets[0].address,
            {"targets": [t.model_dump() for t in req.targets], "hops": req.hops},
        )

    hops = min(req.hops, cfg.max_hops)
    cap = min(req.cap_per_address, 100)

    tr = await trace_multi_hop(req.targets, hops, cap, cfg, req.include_unconfirmed)

    if not tr.edges:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no transactions found for the supplied addresses",
                "hint": "These addresses may be unused, or a provider may be "
                        "unreachable. No placeholder data is returned.",
                "providerErrors": tr.errors,
                "targets": [t.model_dump() for t in req.targets],
            },
        )

    chains = sorted({e.chain for e in tr.edges})
    all_addrs = sorted({a for e in tr.edges for a in (e.from_address, e.to_address)})

    persisted = {"wallets": 0, "transactions": 0}
    wallets: dict = {}
    flags: dict = {}
    if req.persist:
        try:
            persisted = await sb.persist_edges(tr.edges)
            wallets, flags = await sb.entity_flags(chains, all_addrs)
        except Exception as e:                              # noqa: BLE001
            # Persistence is not the deliverable; the graph is. Degrade
            # rather than denying the officer their trace.
            log.error("persistence failed: %s", e)
            tr.errors.append(f"persistence unavailable: {e}")

    scores: dict = {}
    mode = "none"
    if req.score:
        primary = req.targets[0].chain
        try:
            ml = await sb.score_with_ml(
                primary, all_addrs,
                [e for e in tr.edges if e.chain == primary], flags or {})
        except Exception as e:                              # noqa: BLE001
            log.error("ML scoring failed: %s", e)
            ml = None

        if ml:
            scores, mode = ml, "ml"
            try:
                await sb.save_predictions(primary, ml)
            except Exception as e:                          # noqa: BLE001
                log.error("prediction persistence failed: %s", e)
        else:
            # Degrade to the deterministic SQL engine. An officer with
            # rule-based scores is far better served than an error page,
            # and scoringMode says honestly which one this is.
            mode = "rules_only"
            for c in chains:
                try:
                    await sb.rpc("run_detection_pipeline", {"p_chain": c})
                except Exception as e:                      # noqa: BLE001
                    log.error("rules pipeline failed for %s: %s", c, e)

    graph = build_graph(tr, req.targets, wallets, scores)

    return TraceResponse(
        ok=True, targets=req.targets, hops=hops, chains=chains,
        stats={
            "edgesTraced": len(tr.edges),
            "addressesDiscovered": len(tr.visited),
            "nodes": len(graph["nodes"]), "graphEdges": len(graph["edges"]),
            "totalValueUsd": round(sum(e.value_usd for e in tr.edges), 2),
            "walletsPersisted": persisted["wallets"],
            "transactionsPersisted": persisted["transactions"],
            "scored": len(scores), "scoringMode": mode,
        },
        prices={
            "usd": tr.prices,
            "note": "current spot rate applied to all transfers; "
                    "not historical cost basis",
        },
        providerErrors=tr.errors,
        graph=graph,
        elapsedMs=int((time.perf_counter() - t0) * 1000),
    )
