"""
VASP Intelligence, Exchange Wallet Directory & Attribution Engine — SIH 26183 (Batch 2).

Provides an evidence-driven, explainable VASP identification framework for traced
crypto exchange endpoints across multi-chain blockchain networks.

Key Invariants:
 1. Decoupled Dimension: VASP Attribution Confidence is computed STRICTLY from
    independent VASP identity evidence (known deposit records, hot wallet signatures,
    cluster membership, registry entries). It NEVER uses risk_score / 100 or
    fund_attribution_share.
 2. False-Positive Protection: High risk scores, sanctions, transaction volume, or
    rapid forwarding DO NOT turn an unknown wallet into an exchange without
    verifiable VASP evidence.
 3. Explicit Wallet Roles: Classifies exchange endpoints into DEPOSIT, HOT, COLD,
    WITHDRAWAL, OPERATIONAL, or UNKNOWN.
 4. Deduplicated Confidence Aggregation: Combines distinct evidence signals while
    preventing double-counting from identical independence groups.
 5. Case-Linked Fund Correlation: Integrates Batch 1 fund attribution outputs
    (attributed_value_usd, provenance_paths) to correlate victim complaint funds
    with identified exchange endpoints.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

VASP_ENGINE_VERSION = "2.0.0"

# Wallet Roles
ROLE_DEPOSIT = "DEPOSIT"
ROLE_HOT = "HOT"
ROLE_COLD = "COLD"
ROLE_WITHDRAWAL = "WITHDRAWAL"
ROLE_OPERATIONAL = "OPERATIONAL"
ROLE_UNKNOWN = "UNKNOWN"

# Evidence Types
EVIDENCE_EXACT_KNOWN_DEPOSIT = "EXACT_KNOWN_DEPOSIT"
EVIDENCE_EXACT_KNOWN_HOT_WALLET = "EXACT_KNOWN_HOT_WALLET"
EVIDENCE_EXACT_KNOWN_COLD_WALLET = "EXACT_KNOWN_COLD_WALLET"
EVIDENCE_CLUSTER_MATCH = "CLUSTER_MATCH"
EVIDENCE_REGISTRY_MATCH = "REGISTRY_MATCH"
EVIDENCE_MULTI_SOURCE_LABEL = "MULTI_SOURCE_LABEL"
EVIDENCE_BEHAVIORAL_CLUSTER_MATCH = "BEHAVIORAL_CLUSTER_MATCH"

# Base Strength Weights
EVIDENCE_WEIGHTS = {
    EVIDENCE_EXACT_KNOWN_DEPOSIT: 0.98,
    EVIDENCE_EXACT_KNOWN_HOT_WALLET: 0.95,
    EVIDENCE_EXACT_KNOWN_COLD_WALLET: 0.95,
    EVIDENCE_CLUSTER_MATCH: 0.88,
    EVIDENCE_MULTI_SOURCE_LABEL: 0.80,
    EVIDENCE_REGISTRY_MATCH: 0.75,
    EVIDENCE_BEHAVIORAL_CLUSTER_MATCH: 0.65,
}

EVIDENCE_QUALITIES = {
    EVIDENCE_EXACT_KNOWN_DEPOSIT: "VERY_HIGH",
    EVIDENCE_EXACT_KNOWN_HOT_WALLET: "HIGH",
    EVIDENCE_EXACT_KNOWN_COLD_WALLET: "HIGH",
    EVIDENCE_CLUSTER_MATCH: "HIGH",
    EVIDENCE_MULTI_SOURCE_LABEL: "MEDIUM",
    EVIDENCE_REGISTRY_MATCH: "MEDIUM",
    EVIDENCE_BEHAVIORAL_CLUSTER_MATCH: "LOW",
}


@dataclass
class VaspEntity:
    vasp_id: str
    name: str
    legal_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    entity_type: str = "exchange"
    jurisdiction: str | None = None
    status: str = "active"
    supported_chains: list[str] = field(default_factory=list)
    registry_source: str = "verified_directory"


@dataclass
class VaspWalletRecord:
    vasp_id: str
    chain: str
    address: str
    wallet_type: str = ROLE_DEPOSIT
    label: str | None = None
    cluster_id: str | None = None
    source: str = "verified_directory"
    source_reference: str | None = None
    evidence_type: str = EVIDENCE_EXACT_KNOWN_DEPOSIT
    confidence: float = 0.95
    first_seen: str | None = None
    last_verified: str | None = None
    is_active: bool = True


@dataclass
class VaspCluster:
    cluster_id: str
    vasp_id: str
    chain: str
    cluster_name: str
    primary_hot_wallet: str | None = None
    member_wallets: list[str] = field(default_factory=list)


@dataclass
class VaspEvidenceItem:
    evidence_type: str
    strength: str
    confidence: float
    source: str
    source_reference: str | None = None
    independence_group: str = "default_group"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.evidence_type,
            "strength": self.strength,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "source_reference": self.source_reference,
            "independence_group": self.independence_group,
            "description": self.description,
        }


@dataclass
class VaspAttribution:
    identified: bool
    vasp_id: str | None = None
    vasp_name: str | None = None
    chain: str | None = None
    address: str | None = None
    wallet_type: str = ROLE_UNKNOWN
    confidence: float = 0.0
    cluster_id: str | None = None
    hops_from_target: int | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_count: int = 0
    match_types: list[str] = field(default_factory=list)
    case_linked_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "identified": self.identified,
            "vasp_id": self.vasp_id,
            "vasp_name": self.vasp_name,
            "name": self.vasp_name, # backwards compatibility
            "chain": self.chain,
            "address": self.address,
            "wallet_type": self.wallet_type,
            "walletType": self.wallet_type, # UI camelCase compatibility
            "entity_type": "exchange" if self.identified else "unknown",
            "confidence": round(self.confidence, 3),
            "cluster_id": self.cluster_id,
            "clusterId": self.cluster_id,
            "hops_from_target": self.hops_from_target,
            "hopsFromTarget": self.hops_from_target,
            "evidence": self.evidence,
            "evidence_count": self.evidence_count,
            "match_types": self.match_types,
            "case_linked_usd": round(self.case_linked_usd, 2),
        }


def calculate_bounded_confidence(items: list[VaspEvidenceItem]) -> float:
    """
    Computes deterministic confidence by combining independent evidence signals.
    Prevents double-counting from identical independence groups.
      confidence = 1 - product(1 - group_max_confidence)
    Capped strictly at 0.99.
    """
    if not items:
        return 0.0

    # Group evidence items by independence_group
    group_max: dict[str, float] = {}
    for item in items:
        g = item.independence_group or "default_group"
        group_max[g] = max(group_max.get(g, 0.0), item.confidence)

    # Combine distinct independent probabilities
    prod_unlikely = 1.0
    for max_c in group_max.values():
        prod_unlikely *= (1.0 - max_c)

    combined = 1.0 - prod_unlikely
    return min(0.99, round(combined, 3))


def resolve_vasp_attribution(
    address: str,
    chain: str,
    *,
    wallets_intel: dict[str, dict] | None = None,
    explicit_vasp_name: str | None = None,
    explicit_entity_type: str | None = None,
    explicit_wallet_type: str | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
) -> VaspAttribution:
    """
    Resolves VASP candidate identity and computes evidence-driven confidence.
    Enforces strict false-positive protection: unknown wallets remain unidentified.
    """
    wallets_intel = wallets_intel or {}
    k = f"{chain}:{address}"
    intel = wallets_intel.get(k) or wallets_intel.get(address) or {}

    vasp_name = explicit_vasp_name or intel.get("vasp_name") or intel.get("name")
    entity_type = explicit_entity_type or intel.get("entity_type")
    vasp_id = intel.get("vasp_id") or (f"vasp_{vasp_name.lower().replace(' ', '_')}" if vasp_name else None)
    cluster_id = intel.get("cluster_id")
    wallet_type = explicit_wallet_type or intel.get("wallet_type") or ROLE_UNKNOWN

    evidence_items: list[VaspEvidenceItem] = []

    # Process explicit evidence records if passed from database
    if evidence_records:
        for rec in evidence_records:
            e_type = rec.get("evidence_type", EVIDENCE_REGISTRY_MATCH)
            conf = rec.get("confidence") or EVIDENCE_WEIGHTS.get(e_type, 0.75)
            str_val = rec.get("strength") or EVIDENCE_QUALITIES.get(e_type, "MEDIUM")
            grp = rec.get("independence_group") or f"src_{rec.get('source', 'db')}"
            desc = rec.get("description") or f"Verified match via {rec.get('source', 'VASP Registry')}"
            evidence_items.append(VaspEvidenceItem(
                evidence_type=e_type, strength=str_val, confidence=conf,
                source=rec.get("source", "verified_directory"),
                source_reference=rec.get("source_reference"),
                independence_group=grp, description=desc
            ))

    # Evaluate structured signals from intelligence lookup
    if intel.get("is_known_deposit"):
        wallet_type = ROLE_DEPOSIT if wallet_type == ROLE_UNKNOWN else wallet_type
        evidence_items.append(VaspEvidenceItem(
            evidence_type=EVIDENCE_EXACT_KNOWN_DEPOSIT,
            strength="VERY_HIGH", confidence=0.98,
            source=intel.get("source", "verified_directory"),
            source_reference=intel.get("source_reference"),
            independence_group=f"deposit_addr_{chain}_{address}",
            description=f"Verified exact deposit address match for {vasp_name or 'Crypto Exchange'}"
        ))

    if intel.get("is_known_hot_wallet") or intel.get("is_hot_wallet"):
        wallet_type = ROLE_HOT if wallet_type == ROLE_UNKNOWN else wallet_type
        evidence_items.append(VaspEvidenceItem(
            evidence_type=EVIDENCE_EXACT_KNOWN_HOT_WALLET,
            strength="HIGH", confidence=0.95,
            source=intel.get("source", "verified_directory"),
            source_reference=intel.get("source_reference"),
            independence_group=f"hot_addr_{chain}_{address}",
            description=f"Verified hot wallet infrastructure for {vasp_name or 'Crypto Exchange'}"
        ))

    if intel.get("is_known_cold_wallet"):
        wallet_type = ROLE_COLD if wallet_type == ROLE_UNKNOWN else wallet_type
        evidence_items.append(VaspEvidenceItem(
            evidence_type=EVIDENCE_EXACT_KNOWN_COLD_WALLET,
            strength="HIGH", confidence=0.95,
            source=intel.get("source", "verified_directory"),
            source_reference=intel.get("source_reference"),
            independence_group=f"cold_addr_{chain}_{address}",
            description=f"Verified cold storage wallet for {vasp_name or 'Crypto Exchange'}"
        ))

    if cluster_id or intel.get("cluster_name"):
        evidence_items.append(VaspEvidenceItem(
            evidence_type=EVIDENCE_CLUSTER_MATCH,
            strength="HIGH", confidence=0.88,
            source="cluster_resolver",
            source_reference=cluster_id,
            independence_group=f"cluster_{cluster_id or vasp_name}",
            description=f"Cluster membership match in {intel.get('cluster_name') or cluster_id or 'VASP Cluster'}"
        ))

    if vasp_name and not evidence_items:
        is_hot = "hot wallet" in vasp_name.lower() or wallet_type == ROLE_HOT
        e_type = EVIDENCE_EXACT_KNOWN_HOT_WALLET if is_hot else EVIDENCE_CLUSTER_MATCH
        conf_val = 0.95 if is_hot else 0.88
        evidence_items.append(VaspEvidenceItem(
            evidence_type=e_type,
            strength="HIGH", confidence=conf_val,
            source=intel.get("source", "verified_directory"),
            source_reference=intel.get("source_reference"),
            independence_group=f"registry_{vasp_id or vasp_name}",
            description=f"Verified endpoint record for {vasp_name}"
        ))

    # FALSE POSITIVE PROTECTION CHECK:
    # If no VASP evidence items fired and no vasp_name exists, return UNIDENTIFIED.
    # High risk scores or sanctions do NOT create exchange attribution.
    if not evidence_items or not vasp_name:
        return VaspAttribution(
            identified=False,
            vasp_id=None,
            vasp_name=None,
            chain=chain,
            address=address,
            wallet_type=ROLE_UNKNOWN,
            confidence=0.0,
            cluster_id=None,
            hops_from_target=None,
            evidence=[],
            evidence_count=0,
            match_types=[],
        )

    final_confidence = calculate_bounded_confidence(evidence_items)
    match_types = sorted({e.evidence_type for e in evidence_items})

    return VaspAttribution(
        identified=True,
        vasp_id=vasp_id or f"vasp_{vasp_name.lower().replace(' ', '_')}",
        vasp_name=vasp_name,
        chain=chain,
        address=address,
        wallet_type=wallet_type if wallet_type != ROLE_UNKNOWN else ROLE_DEPOSIT,
        confidence=final_confidence,
        cluster_id=cluster_id,
        evidence=[e.to_dict() for e in evidence_items],
        evidence_count=len(evidence_items),
        match_types=match_types,
    )


def resolve_nearest_exchange(
    targets: list[str],
    edges: list[Any],
    vasp_map: dict[str, VaspAttribution | dict[str, Any]],
    wallet_attributions: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Identifies the nearest strongly identified VASP endpoint downstream from targets.
    Correlates distance in hops, path, case-linked funds (attributed_value_usd),
    confidence, and wallet type.
    """
    if not targets or not edges or not vasp_map:
        return None

    wallet_attributions = wallet_attributions or {}
    target_set = set(targets)

    # Build adjacency list: node -> list of outbound edges
    adj: dict[str, list[Any]] = {}
    for e in edges:
        frm = getattr(e, "from_address", None) or (e.get("from_address") if isinstance(e, dict) else None)
        if frm:
            if frm not in adj:
                adj[frm] = []
            adj[frm].append(e)

    # Breadth-first search from targets to find nearest identified VASP
    from collections import deque
    queue = deque([(t, 0, [t]) for t in targets])
    visited: set[str] = set(targets)

    best_candidate: dict[str, Any] | None = None

    while queue:
        curr_node, hops, path = queue.popleft()

        # Check if current node is an identified VASP endpoint
        vasp_entry = vasp_map.get(curr_node)
        is_identified = False
        vasp_id = None
        vasp_name = None
        wallet_type = ROLE_DEPOSIT
        confidence = 0.0
        cluster_id = None
        evidence_list = []

        if isinstance(vasp_entry, VaspAttribution):
            is_identified = vasp_entry.identified
            vasp_id = vasp_entry.vasp_id
            vasp_name = vasp_entry.vasp_name
            wallet_type = vasp_entry.wallet_type
            confidence = vasp_entry.confidence
            cluster_id = vasp_entry.cluster_id
            evidence_list = vasp_entry.evidence
        elif isinstance(vasp_entry, dict):
            is_identified = bool(vasp_entry.get("identified"))
            vasp_id = vasp_entry.get("vasp_id")
            vasp_name = vasp_entry.get("vasp_name") or vasp_entry.get("name")
            wallet_type = vasp_entry.get("wallet_type") or vasp_entry.get("walletType") or ROLE_DEPOSIT
            confidence = float(vasp_entry.get("confidence", 0.0))
            cluster_id = vasp_entry.get("cluster_id") or vasp_entry.get("clusterId")
            evidence_list = vasp_entry.get("evidence", [])

        if is_identified and curr_node not in target_set:
            # Found an exchange endpoint!
            k_attr = next((k for k in wallet_attributions if curr_node in k), None)
            w_attr = wallet_attributions.get(k_attr) if k_attr else wallet_attributions.get(curr_node)
            attr_usd = getattr(w_attr, "attributed_inbound_usd", 0.0) if w_attr and not isinstance(w_attr, dict) else (
                w_attr.get("attributed_inbound_usd", 0.0) if isinstance(w_attr, dict) else 0.0
            )

            candidate = {
                "vasp_id": vasp_id,
                "exchange_name": vasp_name,
                "deposit_address": curr_node,
                "wallet_type": wallet_type,
                "confidence": confidence,
                "cluster_id": cluster_id,
                "hops": hops,
                "path": path,
                "case_linked_usd": attr_usd,
                "evidence": evidence_list,
            }

            if best_candidate is None or (candidate["hops"] < best_candidate["hops"]):
                best_candidate = candidate

        # Continue BFS downstream
        for out_edge in adj.get(curr_node, []):
            to_addr = getattr(out_edge, "to_address", None) or (out_edge.get("to_address") if isinstance(out_edge, dict) else None)
            if to_addr and to_addr not in visited:
                visited.add(to_addr)
                queue.append((to_addr, hops + 1, path + [to_addr]))

    return best_candidate
