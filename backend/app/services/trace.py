"""
Multi-hop tracing and graph construction.

Two design choices worth defending:

  * Highest-value-first expansion. When a hop discovers more counterparties
    than the budget allows, we expand the ones carrying the most value.
    Following the money is the investigative priority; an arbitrary slice
    would just as likely follow dust.

  * Parallel edges are aggregated. A hundred separate lines between two
    nodes is unreadable. One line labelled "$412,000 · 103 tx" is evidence.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from ..config import Settings
from ..providers.adapters import address_history
from ..providers.base import (
    HttpClient, NormEdge, PriceCache, ProviderError, explorer_url, tx_explorer_url,
)
from ..schemas import Target

log = logging.getLogger("chakravyuh.trace")


@dataclass
class TraceResult:
    edges: list[NormEdge] = field(default_factory=list)
    visited: dict[str, int] = field(default_factory=dict)   # "chain:addr" -> hop
    errors: list[str] = field(default_factory=list)
    prices: dict[str, float] = field(default_factory=dict)
    # Addresses the providers refused to answer for. These are the reason a
    # node count can differ between two runs of the SAME trace, so they are
    # reported rather than quietly dropped: an officer must be able to tell
    # "this wallet has no counterparties" from "we could not look".
    dropped: list[str] = field(default_factory=list)
    upstream: dict[str, int] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.dropped


async def trace_multi_hop(
    targets: list[Target], hops: int, cap: int, cfg: Settings,
    include_unconfirmed: bool = False,
) -> TraceResult:
    result = TraceResult()
    seen_edges: set[str] = set()
    history_cache: dict[str, list[NormEdge]] = {}

    async with HttpClient(cfg) as http:
        prices = PriceCache(cfg)
        for chain in {t.chain for t in targets}:
            result.prices[chain] = await prices.get(chain, http)

        frontier = [(t.chain, t.address) for t in targets]
        for c, a in frontier:
            result.visited[f"{c}:{a}"] = 0

        for depth in range(hops + 1):
            if not frontier or len(result.edges) >= cfg.max_total_edges:
                break

            px_for = {}
            for c, _ in frontier:
                if c not in px_for:
                    px_for[c] = result.prices.get(c) or await prices.get(c, http)

            cur_cap = max(cap, 100) if depth == 0 else min(cap, 20)

            async def fetch_one(chain: str, addr: str) -> list[NormEdge]:
                cache_key = f"{chain}:{addr}:{cur_cap}:{include_unconfirmed}"
                if cache_key in history_cache:
                    return history_cache[cache_key]
                edges = await address_history(
                    chain, addr, cur_cap, http, cfg, px_for[chain], include_unconfirmed
                )
                history_cache[cache_key] = edges
                return edges

            tasks = [fetch_one(c, a) for c, a in frontier]
            settled = await asyncio.gather(*tasks, return_exceptions=True)

            next_layer: dict[str, tuple[str, str]] = {}
            for (chain, addr), outcome in zip(frontier, settled):
                if isinstance(outcome, Exception):
                    msg = (str(outcome) if isinstance(outcome, ProviderError)
                           else f"[{chain}] {outcome}")
                    result.errors.append(f"{addr[:14]}… {msg}")
                    result.dropped.append(f"{chain}:{addr}")
                    log.warning("trace failure %s:%s — %s", chain, addr, outcome)
                    continue

                for e in outcome:
                    if e.key in seen_edges:
                        continue
                    seen_edges.add(e.key)
                    result.edges.append(e)

                    if depth < hops:
                        for nb in (e.from_address, e.to_address):
                            k = f"{e.chain}:{nb}"
                            if k not in result.visited and k not in next_layer:
                                next_layer[k] = (e.chain, nb)

            # rank the next layer by the value flowing through each address
            value_of: dict[str, float] = {}
            for e in result.edges:
                for a in (e.from_address, e.to_address):
                    k = f"{e.chain}:{a}"
                    value_of[k] = value_of.get(k, 0.0) + e.value_usd

            # Filter for meaningful counterparties (value > 0 or top ranked)
            ranked = sorted(next_layer.items(),
                            key=lambda kv: (-value_of.get(kv[0], 0.0), kv[0]))
            
            # Limit branch factor per hop for fast execution while keeping critical path
            branch_limit = cfg.max_addresses_per_hop if depth == 0 else min(5, cfg.max_addresses_per_hop)
            frontier = []
            for k, (c, a) in ranked[:branch_limit]:
                result.visited[k] = depth + 1
                frontier.append((c, a))

        result.upstream = dict(http.stats)

    return result


# =====================================================================
def build_graph(
    tr: TraceResult, targets: list[Target],
    wallets: dict[str, dict] | None = None,
    scores: dict[str, dict] | None = None,
) -> dict:
    """React Flow-ready {nodes, edges}."""
    wallets = wallets or {}
    scores = scores or {}
    target_keys = {f"{t.chain}:{t.address}" for t in targets}
    target_addrs = {t.address for t in targets}

    agg: dict[str, dict] = {}
    for e in tr.edges:
        k = f"{e.chain}:{e.from_address}->{e.to_address}"
        a = agg.get(k)
        if a:
            a["value_usd"] += e.value_usd
            a["count"] += 1
            a["first"] = min(a["first"], e.block_time)
            a["last"] = max(a["last"], e.block_time)
            if len(a["hashes"]) < 5:
                a["hashes"].append(e.tx_hash)
        else:
            agg[k] = {"chain": e.chain, "from": e.from_address, "to": e.to_address,
                      "value_usd": e.value_usd, "count": 1,
                      "first": e.block_time, "last": e.block_time,
                      "hashes": [e.tx_hash]}

    node_keys: set[str] = set()
    for a in agg.values():
        node_keys.add(f"{a['chain']}:{a['from']}")
        node_keys.add(f"{a['chain']}:{a['to']}")

    nodes = []
    for k in sorted(node_keys):
        chain, address = k.split(":", 1)
        w = wallets.get(k, {})
        s = scores.get(address, {})
        is_target = k in target_keys

        in_usd = out_usd = 0.0
        degree = 0
        for a in agg.values():
            if a["chain"] != chain:
                continue
            if a["to"] == address:
                in_usd += a["value_usd"]; degree += 1
            if a["from"] == address:
                out_usd += a["value_usd"]; degree += 1

        vasp = (s.get("vasp_attribution") or {})
        entity = w.get("entity_type") if w.get("entity_type") not in (None, "unknown") \
            else (vasp.get("type") if vasp and not vasp.get("abstained") else "unknown")

        nodes.append({
            "id": k,
            "type": "target" if is_target else (entity if entity != "unknown" else "wallet"),
            "data": {
                "address": address, "chain": chain,
                "label": w.get("vasp_name") or f"{address[:8]}…{address[-4:]}",
                "hop": tr.visited.get(k),
                "isTarget": is_target,
                "entity": entity or "unknown",
                "vaspName": w.get("vasp_name"),
                "sanctioned": bool(w.get("is_sanctioned")),
                "riskScore": s.get("risk_score"),
                "riskBand": s.get("risk_band"),
                "narrative": s.get("narrative"),
                "typologies": s.get("typologies", []),
                "recommendedActions": s.get("recommended_actions", []),
                # `factors` is the heuristic breakdown every wallet always
                # has; `explanation` is the model's SHAP view, present only
                # when the ML service answered.
                "factors": s.get("factors", []),
                "explanation": s.get("ml_explanation", s.get("explanation", [])),
                "illicitProbability": s.get("illicit_probability"),
                "anomalyScore": s.get("anomaly_score"),
                "peelDepth": s.get("peel_chain_depth"),
                "hopsToExchange": s.get("hops_to_exchange"),
                "hopsToSanctioned": s.get("hops_to_sanctioned"),
                "hopsToMixer": s.get("hops_to_mixer"),
                "inUsd": round(in_usd, 2), "outUsd": round(out_usd, 2),
                "degree": degree,
                "explorerUrl": explorer_url(chain, address),
            },
        })

    edges = []
    for i, a in enumerate(agg.values()):
        v = a["value_usd"]
        edges.append({
            "id": f"e{i}",
            "source": f"{a['chain']}:{a['from']}",
            "target": f"{a['chain']}:{a['to']}",
            "label": f"${v:,.0f}" if v >= 1 else f"{a['count']} tx",
            "animated": v > 10_000,
            "data": {
                "chain": a["chain"], "valueUsd": round(v, 2), "txCount": a["count"],
                "firstSeen": a["first"], "lastSeen": a["last"],
                "txHashes": a["hashes"],
                # every line on the graph is clickable through to the real
                # block explorer — the detail that makes the data believable
                "explorerUrls": [tx_explorer_url(a["chain"], h) for h in a["hashes"]],
            },
        })

    return {"nodes": nodes, "edges": edges}
