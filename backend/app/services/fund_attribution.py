"""
Recursive Fund Attribution & Taint Propagation Engine — SIH 26183 (Batch 1).

Provides path-aware, deterministic fund attribution across multi-hop graphs,
splits, merges, mixed wallet balances, and multi-asset transfer pools.

Key Invariants:
  1. Conservation of Value: Attributed downstream funds are bounded by the
     original source attribution pool. Funds are never created from nothing.
  2. Asset Isolation: Transfers on different (chain, asset) pairs are tracked
     in separate balance pools and never cross-contaminated.
  3. Path Provenance & Quality: Every edge attribution tracks method
     (DIRECT_SOURCE, FIFO, PRO_RATA, UNAVAILABLE), quality (DIRECT, HIGH,
     MEDIUM, LOW, UNAVAILABLE), and lineage paths.
  4. Cycle Safety: Loops (A -> B -> C -> A) do not amplify or re-attribute
     consumed funds.
  5. Decoupled Architecture: Attribution represents fund-flow linkage to
     reported complaint funds; it is distinct from risk score and VASP confidence.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..providers.base import NormEdge

ATTRIBUTION_ENGINE_VERSION = "1.0.0"

# Attribution Methods
METHOD_DIRECT_SOURCE = "DIRECT_SOURCE"
METHOD_FIFO = "FIFO"
METHOD_PRO_RATA = "PRO_RATA"
METHOD_UNAVAILABLE = "UNAVAILABLE"

# Attribution Quality Levels
QUALITY_DIRECT = "DIRECT"
QUALITY_HIGH = "HIGH"
QUALITY_MEDIUM = "MEDIUM"
QUALITY_LOW = "LOW"
QUALITY_UNAVAILABLE = "UNAVAILABLE"


@dataclass
class AttributionLot:
    """Represents a discrete lot of attributed funds in a wallet balance."""
    source_address: str
    initial_usd: float
    remaining_usd: float
    initial_native: float
    remaining_native: float
    timestamp: float
    tx_hash: str
    hop: int
    path: tuple[str, ...]
    quality: str
    method: str


@dataclass
class AttributionResult:
    """Attribution metrics for a single transaction (edge)."""
    tx_hash: str
    vout_index: int
    from_address: str
    to_address: str
    chain: str
    asset: str
    value_native: float
    value_usd: float
    attributed_value_native: float
    attributed_value_usd: float
    attribution_share: float               # 0.0 to 1.0 (ratio of tx value)
    source_attribution_share: float        # 0.0 to 1.0 (ratio of source pool)
    hop: int
    path_count: int
    attribution_method: str
    attribution_quality: str
    provenance_paths: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "vout_index": self.vout_index,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "chain": self.chain,
            "asset": self.asset,
            "value_native": round(self.value_native, 6),
            "value_usd": round(self.value_usd, 2),
            "attributed_value_native": round(self.attributed_value_native, 6),
            "attributed_value_usd": round(self.attributed_value_usd, 2),
            "attribution_share": round(self.attribution_share, 4),
            "source_attribution_share": round(self.source_attribution_share, 4),
            "hop": self.hop,
            "path_count": self.path_count,
            "attribution_method": self.attribution_method,
            "attribution_quality": self.attribution_quality,
            "provenance_paths": self.provenance_paths,
            "evidence": self.evidence,
        }


@dataclass
class WalletAttribution:
    """Aggregated fund attribution metrics for a single wallet node."""
    address: str
    chain: str
    attributed_inbound_usd: float = 0.0
    attributed_outbound_usd: float = 0.0
    total_inbound_usd: float = 0.0
    total_outbound_usd: float = 0.0
    attribution_share: float = 0.0
    attribution_quality: str = QUALITY_UNAVAILABLE
    source_paths: list[str] = field(default_factory=list)
    participating_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "chain": self.chain,
            "attributed_inbound_usd": round(self.attributed_inbound_usd, 2),
            "attributed_outbound_usd": round(self.attributed_outbound_usd, 2),
            "total_inbound_usd": round(self.total_inbound_usd, 2),
            "total_outbound_usd": round(self.total_outbound_usd, 2),
            "attribution_share": round(self.attribution_share, 4),
            "attribution_quality": self.attribution_quality,
            "source_paths": self.source_paths,
            "participating_sources": self.participating_sources,
        }


def _epoch(iso_ts: str | None) -> float:
    if not iso_ts:
        return 0.0
    try:
        return datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def compute_fund_attribution(
    edges: list[NormEdge],
    targets: list[str],
    initial_amounts: dict[str, float] | None = None,
) -> tuple[dict[str, AttributionResult], dict[str, WalletAttribution]]:
    """
    Main Attribution Engine Entry Point.

    Computes path-aware, deterministic fund attribution across multi-hop graphs,
    splits, merges, mixed wallet balances, and multi-asset transfer pools.

    Returns:
        (edge_attributions_map, wallet_attributions_map)
        where edge_attributions_map is keyed by `edge.key` (or `chain:tx_hash:vout_index:from:to`).
    """
    if not edges or not targets:
        return {}, {}

    target_set = set(targets)
    initial_amounts = initial_amounts or {}

    # 1. Group edges by (chain, asset) pool for strict asset isolation
    pools: dict[tuple[str, str], list[NormEdge]] = defaultdict(list)
    for e in edges:
        pools[(e.chain, e.asset)].append(e)

    edge_results: dict[str, AttributionResult] = {}
    wallet_results: dict[str, WalletAttribution] = {}

    # Global tracking of wallet totals across pools
    w_inbound: dict[str, float] = defaultdict(float)
    w_outbound: dict[str, float] = defaultdict(float)
    w_attr_inbound: dict[str, float] = defaultdict(float)
    w_attr_outbound: dict[str, float] = defaultdict(float)
    w_paths: dict[str, set[str]] = defaultdict(set)
    w_sources: dict[str, set[str]] = defaultdict(set)
    w_qualities: dict[str, set[str]] = defaultdict(set)

    for (chain, asset), pool_edges in pools.items():
        # 2. Deterministic Chronological / Topological Edge Sorting
        sorted_edges = sorted(
            pool_edges,
            key=lambda e: (
                _epoch(e.block_time),
                e.block_height or 0,
                e.vout_index,
                e.tx_hash,
                e.from_address,
                e.to_address,
            ),
        )

        # 3. Initialize Source Attribution Pools for this (chain, asset)
        wallet_lots: dict[str, list[AttributionLot]] = defaultdict(list)
        wallet_inflow_sum: dict[str, float] = defaultdict(float)

        # Initialize Target Wallets
        for target_addr in targets:
            k_target = f"{chain}:{asset}:{target_addr}"
            target_outbound = sum(e.value_usd for e in sorted_edges if e.from_address == target_addr)
            target_inbound = sum(e.value_usd for e in sorted_edges if e.to_address == target_addr)

            # Determine initial pool USD
            explicit_val = initial_amounts.get(target_addr, 0.0)
            if explicit_val > 0:
                pool_usd = explicit_val
            elif target_outbound > 0:
                pool_usd = target_outbound
            else:
                pool_usd = target_inbound if target_inbound > 0 else 1000.0

            # Estimate native value
            sample_edge = next((e for e in sorted_edges if e.from_address == target_addr or e.to_address == target_addr), None)
            ratio = (sample_edge.value_native / sample_edge.value_usd) if (sample_edge and sample_edge.value_usd > 0) else 1.0
            pool_native = pool_usd * ratio

            init_lot = AttributionLot(
                source_address=target_addr,
                initial_usd=pool_usd,
                remaining_usd=pool_usd,
                initial_native=pool_native,
                remaining_native=pool_native,
                timestamp=min((_epoch(e.block_time) for e in sorted_edges if e.from_address == target_addr), default=0.0),
                tx_hash="INIT_TARGET",
                hop=0,
                path=(target_addr,),
                quality=QUALITY_DIRECT,
                method=METHOD_DIRECT_SOURCE,
            )
            wallet_lots[k_target].append(init_lot)
            wallet_inflow_sum[k_target] += pool_usd

            w_sources[f"{chain}:{target_addr}"].add(target_addr)
            w_paths[f"{chain}:{target_addr}"].add(target_addr)
            w_qualities[f"{chain}:{target_addr}"].add(QUALITY_DIRECT)

        # Total source pool size for this (chain, asset)
        total_asset_source_usd = sum(
            sum(l.initial_usd for l in wallet_lots[f"{chain}:{asset}:{t}"]) for t in targets
        )
        if total_asset_source_usd <= 0:
            total_asset_source_usd = 1.0

        # 4. Propagate Fund Attribution Edge by Edge
        for e in sorted_edges:
            s_addr = e.from_address
            d_addr = e.to_address
            v_usd = e.value_usd
            v_native = e.value_native
            k_s = f"{chain}:{asset}:{s_addr}"
            k_d = f"{chain}:{asset}:{d_addr}"

            wk_s = f"{chain}:{s_addr}"
            wk_d = f"{chain}:{d_addr}"

            w_inbound[wk_d] += v_usd
            w_outbound[wk_s] += v_usd

            available_lots = [l for l in wallet_lots[k_s] if l.remaining_usd > 0.0001]
            available_attr_usd = sum(l.remaining_usd for l in available_lots)

            # Case A: Sender has NO available attributed funds
            if available_attr_usd <= 0.0001:
                wallet_inflow_sum[k_d] += v_usd
                res = AttributionResult(
                    tx_hash=e.tx_hash,
                    vout_index=e.vout_index,
                    from_address=s_addr,
                    to_address=d_addr,
                    chain=chain,
                    asset=asset,
                    value_native=v_native,
                    value_usd=v_usd,
                    attributed_value_native=0.0,
                    attributed_value_usd=0.0,
                    attribution_share=0.0,
                    source_attribution_share=0.0,
                    hop=0,
                    path_count=0,
                    attribution_method=METHOD_UNAVAILABLE,
                    attribution_quality=QUALITY_UNAVAILABLE,
                    evidence=["No attributed funds present in sender balance pool"],
                )
                edge_results[e.key] = res
                continue

            # Case B: Sender HAS attributed funds
            is_direct_target = s_addr in target_set
            tot_inflow = max(wallet_inflow_sum[k_s], available_attr_usd)

            # Determine attribution method & quality
            if is_direct_target:
                method = METHOD_DIRECT_SOURCE
                quality = QUALITY_DIRECT
                attr_ratio = 1.0
            elif available_attr_usd >= 0.95 * tot_inflow:
                # Wallet contains almost purely attributed funds -> FIFO
                method = METHOD_FIFO
                quality = QUALITY_HIGH
                attr_ratio = 1.0
            else:
                # Mixed wallet balances -> Pro-Rata Allocation
                method = METHOD_PRO_RATA
                attr_ratio = min(1.0, available_attr_usd / max(tot_inflow, 1.0))
                quality = QUALITY_HIGH if attr_ratio >= 0.75 else (QUALITY_MEDIUM if attr_ratio >= 0.25 else QUALITY_LOW)

            # Calculate attributed USD and native amounts
            if method == METHOD_PRO_RATA:
                attr_usd = min(available_attr_usd, v_usd * attr_ratio)
            else:
                attr_usd = min(available_attr_usd, v_usd)

            attr_native = (v_native * (attr_usd / v_usd)) if v_usd > 0 else 0.0
            attr_share = min(1.0, attr_usd / max(v_usd, 0.01)) if v_usd > 0 else 0.0
            src_attr_share = min(1.0, attr_usd / total_asset_source_usd)

            # Lot Consumption at Sender (s_addr)
            needed_usd = attr_usd
            consumed_lots: list[tuple[AttributionLot, float]] = []

            for lot in available_lots:
                if needed_usd <= 0.0001:
                    break
                take_usd = min(lot.remaining_usd, needed_usd)
                lot.remaining_usd -= take_usd
                needed_usd -= take_usd
                consumed_lots.append((lot, take_usd))

            # Propagate New Attributed Lots to Destination (d_addr)
            provenance_list: list[dict[str, Any]] = []
            max_hop = 0
            distinct_paths: set[tuple[str, ...]] = set()

            for lot, c_usd in consumed_lots:
                max_hop = max(max_hop, lot.hop + 1)
                # Cycle Safety: Stop propagation if destination is already in lot path
                if d_addr in lot.path:
                    continue

                new_path = lot.path + (d_addr,)
                distinct_paths.add(new_path)
                path_str = " -> ".join(new_path)
                w_paths[wk_d].add(path_str)
                w_sources[wk_d].add(lot.source_address)
                w_qualities[wk_d].add(quality)

                c_native = (v_native * (c_usd / v_usd)) if v_usd > 0 else 0.0
                new_lot = AttributionLot(
                    source_address=lot.source_address,
                    initial_usd=c_usd,
                    remaining_usd=c_usd,
                    initial_native=c_native,
                    remaining_native=c_native,
                    timestamp=_epoch(e.block_time),
                    tx_hash=e.tx_hash,
                    hop=lot.hop + 1,
                    path=new_path,
                    quality=quality,
                    method=method,
                )
                wallet_lots[k_d].append(new_lot)

                provenance_list.append({
                    "source": lot.source_address,
                    "amount_usd": round(c_usd, 2),
                    "hop": lot.hop + 1,
                    "path": path_str,
                })

            wallet_inflow_sum[k_d] += v_usd

            w_attr_inbound[wk_d] += attr_usd
            w_attr_outbound[wk_s] += attr_usd

            # Build Evidence Strings
            ev_list = [
                f"Attributed ${attr_usd:,.2f} USD ({attr_share:.1%} of transfer) via {method} [{quality}]",
                f"Hop {max_hop or 1} downstream from source ({len(distinct_paths)} active path(s))",
            ]
            if method == METHOD_PRO_RATA:
                ev_list.append(f"Pro-rata allocation applied to mixed sender balance (ratio {attr_ratio:.1%})")

            res = AttributionResult(
                tx_hash=e.tx_hash,
                vout_index=e.vout_index,
                from_address=s_addr,
                to_address=d_addr,
                chain=chain,
                asset=asset,
                value_native=v_native,
                value_usd=v_usd,
                attributed_value_native=attr_native,
                attributed_value_usd=attr_usd,
                attribution_share=attr_share,
                source_attribution_share=src_attr_share,
                hop=max_hop or 1,
                path_count=len(distinct_paths),
                attribution_method=method,
                attribution_quality=quality,
                provenance_paths=provenance_list,
                evidence=ev_list,
            )
            edge_results[e.key] = res

    # 5. Build Wallet Attribution Aggregates
    all_wallets = {f"{e.chain}:{a}" for e in edges for a in (e.from_address, e.to_address)}
    for target_addr in targets:
        for chain in {e.chain for e in edges}:
            all_wallets.add(f"{chain}:{target_addr}")

    for wk in sorted(all_wallets):
        chain, addr = wk.split(":", 1)
        tin = w_inbound[wk]
        ain = w_attr_inbound[wk]
        aout = w_attr_outbound[wk]
        tout = w_outbound[wk]

        share = (ain / max(tin, 1.0)) if tin > 0 else (1.0 if addr in target_set else 0.0)

        # Aggregate Quality
        quals = w_qualities[wk]
        if QUALITY_DIRECT in quals or addr in target_set:
            best_q = QUALITY_DIRECT
        elif QUALITY_HIGH in quals:
            best_q = QUALITY_HIGH
        elif QUALITY_MEDIUM in quals:
            best_q = QUALITY_MEDIUM
        elif QUALITY_LOW in quals:
            best_q = QUALITY_LOW
        else:
            best_q = QUALITY_UNAVAILABLE

        wallet_results[wk] = WalletAttribution(
            address=addr,
            chain=chain,
            attributed_inbound_usd=ain,
            attributed_outbound_usd=aout,
            total_inbound_usd=tin,
            total_outbound_usd=tout,
            attribution_share=min(1.0, share),
            attribution_quality=best_q,
            source_paths=sorted(list(w_paths[wk]))[:10],
            participating_sources=sorted(list(w_sources[wk])),
        )

    return edge_results, wallet_results
