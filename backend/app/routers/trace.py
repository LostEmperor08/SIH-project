"""
POST /trace — the authenticated live blockchain trace.

The endpoint the whole platform exists for. No mock path: if the providers
return nothing, this returns 404 with the provider errors attached. It never
substitutes placeholder edges.
"""
from __future__ import annotations

import asyncio
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

    scores: dict = {}
    mode = "none"

    if req.score or req.persist:
        primary = req.targets[0].chain

        # ---- persistence and ML scoring run concurrently ----------------
        # Both are network-bound (Supabase RPC + local ML service). Running
        # them sequentially added the ML wait on top of the DB wait — that is
        # the source of the 25-second latency. asyncio.gather fires both and
        # waits for whichever finishes last, which is ALWAYS faster.
        async def _persist() -> tuple[dict, dict, dict]:
            if not req.persist:
                return {}, {}, {}
            try:
                p = await sb.persist_edges(tr.edges)
                w, f = await sb.entity_flags(chains, all_addrs)
                return p, w, f
            except Exception as exc:                        # noqa: BLE001
                log.error("persistence failed: %s", exc)
                tr.errors.append(f"persistence unavailable: {exc}")
                return {"wallets": 0, "transactions": 0}, {}, {}

        async def _ml_score() -> dict | None:
            if not req.score or not cfg.ml_api_url:
                return None
            try:
                return await sb.score_with_ml(
                    primary, all_addrs,
                    [e for e in tr.edges if e.chain == primary], {})
            except Exception as exc:                        # noqa: BLE001
                log.error("ML scoring failed: %s", exc)
                return None

        (persist_result, ml_result) = await asyncio.gather(
            _persist(), _ml_score()
        )

        persisted, wallets, flags = persist_result
        ml = ml_result

        if req.score:
            # ---- gateway heuristic score (no network, no model needed) --
            scores = score_graph(
                tr.edges,
                [t.address for t in req.targets],
                sanctioned=set(flags.get("sanctioned", [])),
                mixers=set(flags.get("mixers", [])),
                exchanges=set(flags.get("exchanges", [])),
                darknet=set(flags.get("darknet", [])),
            )
            mode = "heuristic"

            # ---- merge ML results over the heuristic baseline ------------
            if ml:
                mode = "ml+heuristic"
                for addr, ml_row in ml.items():
                    base = scores.get(addr, {})
                    base.update({
                        "risk_score": ml_row.get("risk_score", base.get("risk_score")),
                        "risk_band": ml_row.get("risk_band", base.get("risk_band")),
                        "illicit_probability": ml_row.get("illicit_probability"),
                        "anomaly_score": ml_row.get("anomaly_score"),
                        "typologies": ml_row.get("typologies", []),
                        "vasp_attribution": ml_row.get("vasp_attribution"),
                        "ml_explanation": ml_row.get("explanation", []),
                    })
                    # Sanctions floor outranks the model, always.
                    if base.get("sanction_floor_applied"):
                        base["risk_score"] = max(base.get("risk_score") or 0, 90.0)
                        base["risk_band"] = "critical"
                    scores[addr] = base
                try:
                    await sb.save_predictions(primary, scores)
                except Exception as e:                      # noqa: BLE001
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
