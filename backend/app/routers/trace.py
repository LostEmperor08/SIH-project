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
from ..services.risk import score_graph
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
        # ---- always compute the gateway score first ------------------
        # It needs no database and no ML service, so an officer always gets
        # a scored graph. The ML layer refines this when it is reachable;
        # it is not a prerequisite for getting an answer.
        scores = score_graph(
            tr.edges,
            [t.address for t in req.targets],
            sanctioned=set(flags.get("sanctioned", [])),
            mixers=set(flags.get("mixers", [])),
            exchanges=set(flags.get("exchanges", [])),
            darknet=set(flags.get("darknet", [])),
        )
        mode = "heuristic"

        # ---- then let the ML layer refine it, if available ------------
        primary = req.targets[0].chain
        try:
            ml = await sb.score_with_ml(
                primary, all_addrs,
                [e for e in tr.edges if e.chain == primary], flags or {})
        except Exception as e:                              # noqa: BLE001
            log.error("ML scoring failed: %s", e)
            ml = None

        if ml:
            mode = "ml+heuristic"
            for addr, ml_row in ml.items():
                base = scores.get(addr, {})
                # Keep the heuristic factors — they are what an officer can
                # verify by hand — and merge the model's view alongside.
                base.update({
                    "risk_score": ml_row.get("risk_score", base.get("risk_score")),
                    "risk_band": ml_row.get("risk_band", base.get("risk_band")),
                    "illicit_probability": ml_row.get("illicit_probability"),
                    "anomaly_score": ml_row.get("anomaly_score"),
                    "typologies": ml_row.get("typologies", []),
                    "vasp_attribution": ml_row.get("vasp_attribution"),
                    "ml_explanation": ml_row.get("explanation", []),
                })
                # The sanctions floor outranks the model, always.
                if base.get("sanction_floor_applied"):
                    base["risk_score"] = max(base.get("risk_score") or 0, 90.0)
                    base["risk_band"] = "critical"
                scores[addr] = base
            try:
                await sb.save_predictions(primary, scores)
            except Exception as e:                          # noqa: BLE001
                log.error("prediction persistence failed: %s", e)

    graph = build_graph(tr, req.targets, wallets, scores)

    # Sort edges chronologically descending (newest first) for forensic investigation
    raw_txs = sorted(
        [e.to_row() for e in tr.edges],
        key=lambda r: str(r.get("block_time") or ""),
        reverse=True,
    )

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
            # A trace is COMPLETE only if every address on the frontier was
            # answered. When it is not, say so and name the addresses —
            # that is the difference between a smaller graph and a wrong one.
            "complete": tr.complete,
            "addressesUnreachable": len(tr.dropped),
            "upstreamRequests": tr.upstream.get("requests", 0),
            "upstreamCacheHits": tr.upstream.get("cache_hits", 0),
            "rateLimitRetries": tr.upstream.get("rate_limit_retries", 0),
        },
        prices={
            "usd": tr.prices,
            "note": "current spot rate applied to all transfers; "
                    "not historical cost basis",
        },
        providerErrors=tr.errors,
        graph=graph,
        transactions=raw_txs,
        elapsedMs=int((time.perf_counter() - t0) * 1000),
    )
