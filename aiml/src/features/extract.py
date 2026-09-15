"""
Feature extraction: Supabase transaction graph -> model-ready matrix.

Two entry points:
  build_from_supabase(chain)   -- training: pull everything, batch compute
  build_for_addresses(edges, addrs) -- serving: compute for a handful of
                                       wallets from an already-fetched subgraph

Both funnel through _compute(), so a feature can never be defined two
different ways.  This is the anti-skew guarantee that schema.py promises.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .schema import FEATURE_NAMES, NO_PATH, validate_frame

SECONDS_PER_DAY = 86_400.0


# =====================================================================
# Edge container
# =====================================================================
@dataclass
class Edge:
    src: str
    dst: str
    value_usd: float
    ts: float                # unix seconds
    tx_hash: str = ""


# =====================================================================
# Graph helpers
# =====================================================================
def _bfs_hops(
    adj: dict[str, set[str]],
    targets: set[str],
    max_hops: int = 6,
) -> dict[str, int]:
    """
    Multi-source BFS from every flagged address outwards.

    Running it backwards from the targets (rather than forwards from each
    wallet) turns N single-source searches into one traversal -- the
    difference between O(N*E) and O(E), which is what makes this usable on
    a live graph rather than a toy one.
    """
    dist: dict[str, int] = {t: 0 for t in targets if t in adj}
    q = deque(dist)
    while q:
        node = q.popleft()
        d = dist[node]
        if d >= max_hops:
            continue
        for nb in adj.get(node, ()):
            if nb not in dist:
                dist[nb] = d + 1
                q.append(nb)
    return dist


def _entropy(counts) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    return float(-sum((c / total) * math.log(c / total) for c in counts if c > 0))


def _peel_depth(adj_out: dict[str, list[Edge]], start: str, max_depth: int = 12) -> int:
    """
    Longest chain where each hop forwards 70-98% of what it received --
    value bleeding off a little at a time. This is the peel chain, the
    dominant layering pattern in task-based and investment fraud.
    """
    best = 0
    stack: list[tuple[str, float, int, set[str]]] = [(start, math.inf, 0, {start})]
    while stack:
        node, prev_val, depth, seen = stack.pop()
        if depth > best:
            best = depth
        if depth >= max_depth:
            continue
        for e in adj_out.get(node, ())[:8]:          # cap fan-out per level
            if e.dst in seen:
                continue
            if prev_val == math.inf or (0.70 * prev_val <= e.value_usd <= 0.98 * prev_val):
                stack.append((e.dst, e.value_usd, depth + 1, seen | {e.dst}))
    return best


# =====================================================================
# Core computation
# =====================================================================
def _compute(
    edges: list[Edge],
    addresses: list[str] | None = None,
    *,
    sanctioned: set[str] | None = None,
    mixers: set[str] | None = None,
    exchanges: set[str] | None = None,
    darknet: set[str] | None = None,
    bridges: set[str] | None = None,
    cluster_of: dict[str, str] | None = None,
    cluster_sizes: dict[str, int] | None = None,
    now_ts: float | None = None,
) -> pd.DataFrame:
    """Compute the full feature matrix. Pure function -- easy to unit test."""
    sanctioned = sanctioned or set()
    mixers = mixers or set()
    exchanges = exchanges or set()
    darknet = darknet or set()
    bridges = bridges or set()
    cluster_of = cluster_of or {}
    cluster_sizes = cluster_sizes or {}
    now_ts = now_ts or (max((e.ts for e in edges), default=0.0) + 1)

    out_e: dict[str, list[Edge]] = defaultdict(list)
    in_e: dict[str, list[Edge]] = defaultdict(list)
    adj: dict[str, set[str]] = defaultdict(set)

    for e in edges:
        out_e[e.src].append(e)
        in_e[e.dst].append(e)
        adj[e.src].add(e.dst)
        adj[e.dst].add(e.src)          # undirected for proximity search

    if addresses is None:
        addresses = sorted(set(out_e) | set(in_e))

    hops = {
        "sanction_hops": _bfs_hops(adj, sanctioned),
        "mixer_hops": _bfs_hops(adj, mixers),
        "exchange_hops": _bfs_hops(adj, exchanges),
        "darknet_hops": _bfs_hops(adj, darknet),
    }

    # taint flows forward only: value arriving FROM a flagged source
    flagged = sanctioned | mixers | darknet
    taint_hops = _bfs_hops(adj, flagged, max_hops=5)

    rows: list[dict] = []
    for addr in addresses:
        oe, ie = out_e.get(addr, []), in_e.get(addr, [])
        all_e = oe + ie
        if not all_e:
            rows.append({"address": addr, **{f: 0.0 for f in FEATURE_NAMES}})
            continue

        in_vals = np.array([e.value_usd for e in ie], dtype=float)
        out_vals = np.array([e.value_usd for e in oe], dtype=float)
        all_vals = np.array([e.value_usd for e in all_e], dtype=float)
        times = np.array(sorted(e.ts for e in all_e), dtype=float)

        total_in = float(in_vals.sum())
        total_out = float(out_vals.sum())
        span_days = max((times[-1] - times[0]) / SECONDS_PER_DAY, 1e-6)

        senders = {e.src for e in ie}
        receivers = {e.dst for e in oe}
        both = senders & receivers

        cp_counts = defaultdict(int)
        for e in ie:
            cp_counts[e.src] += 1
        for e in oe:
            cp_counts[e.dst] += 1

        hour_counts = defaultdict(int)
        night = weekend = 0
        for e in all_e:
            import datetime as _dt
            d = _dt.datetime.utcfromtimestamp(e.ts)
            hour_counts[d.hour] += 1
            if d.hour < 5:
                night += 1
            if d.weekday() >= 5:
                weekend += 1

        gaps = np.diff(times) if times.size > 1 else np.array([0.0])
        g_mean = float(gaps.mean()) if gaps.size else 0.0
        g_std = float(gaps.std()) if gaps.size else 0.0

        own_cluster = cluster_of.get(addr)
        self_loops = sum(
            1 for e in all_e
            if own_cluster
            and cluster_of.get(e.dst if e.src == addr else e.src) == own_cluster
        )

        out_mean = float(out_vals.mean()) if out_vals.size else 0.0
        out_std = float(out_vals.std()) if out_vals.size else 0.0

        th = taint_hops.get(addr, NO_PATH)
        # taint decays by half per hop -- a wallet six hops from a mixer is
        # not the same as one transacting with it directly
        max_taint = 0.0 if th >= NO_PATH else 0.5 ** th
        tainted_in = sum(
            e.value_usd for e in ie
            if taint_hops.get(e.src, NO_PATH) <= 2
        )

        rows.append({
            "address": addr,
            # volume
            "total_in_usd": total_in,
            "total_out_usd": total_out,
            "balance_usd": total_in - total_out,
            "avg_value_usd": float(all_vals.mean()),
            "value_stddev_usd": float(all_vals.std()),
            "max_value_usd": float(all_vals.max()),
            "in_out_ratio": total_in / (total_out + 1.0),
            # velocity
            "tx_count": float(len(all_e)),
            "tx_velocity": len(all_e) / span_days,
            "active_days": span_days,
            "dormancy_days": (now_ts - times[-1]) / SECONDS_PER_DAY,
            "lifespan_ratio": span_days / max((now_ts - times[0]) / SECONDS_PER_DAY, 1e-6),
            # topology
            "fan_in": float(len(senders)),
            "fan_out": float(len(receivers)),
            "fan_ratio": len(senders) / (len(receivers) + 1.0),
            "counterparty_entropy": _entropy(list(cp_counts.values())),
            "unique_cp_ratio": len(cp_counts) / len(all_e),
            "cluster_size": float(cluster_sizes.get(own_cluster, 1)) if own_cluster else 1.0,
            "degree_centrality": len(adj.get(addr, ())) / max(len(adj), 1),
            "reciprocity": len(both) / max(len(senders | receivers), 1),
            # temporal
            "night_activity_ratio": night / len(all_e),
            "weekend_ratio": weekend / len(all_e),
            "inter_tx_burstiness": g_std / g_mean if g_mean > 0 else 0.0,
            "hour_entropy": _entropy(list(hour_counts.values())),
            "first_seen_age_days": (now_ts - times[0]) / SECONDS_PER_DAY,
            # taint
            "sanction_hops": float(hops["sanction_hops"].get(addr, NO_PATH)),
            "mixer_hops": float(hops["mixer_hops"].get(addr, NO_PATH)),
            "exchange_hops": float(hops["exchange_hops"].get(addr, NO_PATH)),
            "darknet_hops": float(hops["darknet_hops"].get(addr, NO_PATH)),
            "max_taint_share": max_taint,
            "tainted_inflow_ratio": tainted_in / (total_in + 1.0),
            # structuring
            "peel_chain_depth": float(_peel_depth(out_e, addr)),
            "round_amount_ratio": float(
                np.mean([(v > 0 and v % 100 == 0) for v in all_vals])),
            "structuring_score": float(
                np.mean([(8000 <= v <= 9999) for v in all_vals])),
            "uniform_output_score": max(0.0, 1.0 - out_std / out_mean) if out_mean > 0 else 0.0,
            "self_loop_ratio": self_loops / len(all_e),
            "cross_chain_flag": float(
                any(e.dst in bridges or e.src in bridges for e in all_e)),
        })

    df = pd.DataFrame(rows).fillna(0.0)
    for col in FEATURE_NAMES:
        if col not in df.columns:
            df[col] = 0.0
    df = df[["address"] + FEATURE_NAMES]
    validate_frame(df)
    return df


# =====================================================================
# Public entry points
# =====================================================================
def build_for_addresses(edges: list[Edge], addresses: list[str], **kw) -> pd.DataFrame:
    """Serving path: score specific wallets from a fetched subgraph."""
    return _compute(edges, addresses, **kw)


def build_from_supabase(chain: str = "btc", lookback_days: int = 180) -> pd.DataFrame:
    """
    Training path: pull the full transaction graph for one chain.

    Paginates because PostgREST caps a single response; a silent truncation
    here would quietly train the model on a fraction of the graph.
    """
    from supabase import create_client

    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )

    since = (pd.Timestamp.utcnow() - pd.Timedelta(days=lookback_days)).isoformat()

    edges: list[Edge] = []
    page, size = 0, 1000
    while True:
        res = (sb.table("transactions")
                 .select("from_address,to_address,value_usd,block_time,tx_hash")
                 .eq("chain", chain)
                 .gte("block_time", since)
                 .range(page * size, (page + 1) * size - 1)
                 .execute())
        batch = res.data or []
        edges.extend(
            Edge(r["from_address"], r["to_address"], float(r["value_usd"] or 0),
                 pd.Timestamp(r["block_time"]).timestamp(), r.get("tx_hash", ""))
            for r in batch
        )
        if len(batch) < size:
            break
        page += 1

    if not edges:
        raise RuntimeError(
            f"no transactions found for chain={chain}. "
            "Run the ingest-chain edge function first."
        )

    # entity sets used for proximity features
    def _addrs(table: str, **filters) -> set[str]:
        q = sb.table(table).select("address").eq("chain", chain)
        for k, v in filters.items():
            q = q.eq(k, v)
        return {r["address"] for r in (q.execute().data or [])}

    wallets = sb.table("wallets").select(
        "address,entity_type,is_sanctioned").eq("chain", chain).execute().data or []

    sanctioned = {w["address"] for w in wallets if w["is_sanctioned"]}
    mixers = {w["address"] for w in wallets if w["entity_type"] == "mixer"}
    exchanges = {w["address"] for w in wallets if w["entity_type"] == "exchange"}
    darknet = {w["address"] for w in wallets if w["entity_type"] == "darknet"}
    bridges = {w["address"] for w in wallets if w["entity_type"] == "bridge"}
    sanctioned |= _addrs("threat_intel", category="sanctioned")

    # cluster membership
    cm = sb.table("cluster_members").select(
        "cluster_id,wallets(address),clusters(root_address,size)").execute().data or []
    cluster_of, cluster_sizes = {}, {}
    for r in cm:
        try:
            addr = r["wallets"]["address"]
            root = r["clusters"]["root_address"]
            cluster_of[addr] = root
            cluster_sizes[root] = r["clusters"]["size"]
        except (KeyError, TypeError):
            continue

    df = _compute(
        edges,
        sanctioned=sanctioned, mixers=mixers, exchanges=exchanges,
        darknet=darknet, bridges=bridges,
        cluster_of=cluster_of, cluster_sizes=cluster_sizes,
    )
    df.insert(1, "chain", chain)
    return df
