"""
Pydantic request/response models — Control 5: strict validation.

Every address is regex-checked against its chain BEFORE any network call.
That is both a correctness measure (no wasted provider quota on typos) and a
security one: these strings end up in upstream URLs, so unvalidated input is
a path-traversal and SSRF vector.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Chain = Literal["btc", "eth", "polygon", "tron", "bsc"]

ADDRESS_PATTERNS: dict[str, re.Pattern] = {
    "btc": re.compile(r"^(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$"),
    "eth": re.compile(r"^0x[a-fA-F0-9]{40}$"),
    "polygon": re.compile(r"^0x[a-fA-F0-9]{40}$"),
    "bsc": re.compile(r"^0x[a-fA-F0-9]{40}$"),
    "tron": re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$"),
}


def is_valid_address(chain: str, address: str) -> bool:
    p = ADDRESS_PATTERNS.get(chain)
    return bool(p and p.match(address))


def normalise_address(chain: str, address: str) -> str:
    a = address.strip()
    return a if chain in ("btc", "tron") else a.lower()


# =====================================================================
# Requests
# =====================================================================
class Target(BaseModel):
    chain: Chain
    address: str = Field(min_length=20, max_length=128)

    @model_validator(mode="after")
    def _check(self) -> "Target":
        if not is_valid_address(self.chain, self.address.strip()):
            raise ValueError(f"'{self.address}' is not a valid {self.chain} address")
        object.__setattr__(self, "address", normalise_address(self.chain, self.address))
        return self


class TraceRequest(BaseModel):
    """POST /trace"""
    targets: list[Target] = Field(min_length=1, max_length=10)
    hops: int = Field(default=2, ge=0, le=3)
    cap_per_address: int = Field(default=50, ge=1, le=100)
    include_unconfirmed: bool = False
    score: bool = True
    persist: bool = True

    @field_validator("targets")
    @classmethod
    def _unique(cls, v: list[Target]) -> list[Target]:
        seen = {(t.chain, t.address) for t in v}
        if len(seen) != len(v):
            raise ValueError("duplicate targets")
        return v


class ThreatIntelSyncRequest(BaseModel):
    """POST /threat-intel/sync"""
    sources: list[Literal["ofac", "custom"]] = Field(default=["ofac"])
    force: bool = False


class DossierReviewRequest(BaseModel):
    """POST /dossier/review — admin only"""
    dossier_id: str = Field(min_length=1, max_length=64)
    decision: Literal["approved", "rejected", "returned"]
    remarks: str | None = Field(default=None, max_length=4000)


# =====================================================================
# Responses
# =====================================================================
class GraphNodeData(BaseModel):
    address: str
    chain: str
    label: str
    hop: int | None = None
    isTarget: bool = False
    entity: str = "unknown"
    vaspName: str | None = None
    vaspAttribution: dict[str, Any] | None = None
    sanctioned: bool = False
    riskScore: float | None = None
    riskBand: str | None = None
    sanctionFloorApplied: bool = False
    sanctionFloorReason: str | None = None
    transactionAggregates: dict[str, Any] = {}
    narrative: str | None = None
    typologies: list[dict[str, Any]] = []
    recommendedActions: list[str] = []
    factors: list[dict[str, Any]] = []
    explanation: list[dict[str, Any]] = []
    illicitProbability: float | None = None
    anomalyScore: float | None = None
    peelDepth: int | None = None
    hopsToExchange: int | None = None
    hopsToSanctioned: int | None = None
    hopsToMixer: int | None = None
    inUsd: float = 0.0
    outUsd: float = 0.0
    degree: int = 0
    explorerUrl: str | None = None


class GraphNode(BaseModel):
    id: str
    type: str = "wallet"
    data: GraphNodeData


class GraphEdgeData(BaseModel):
    chain: str
    valueUsd: float
    txCount: int
    firstSeen: str | None = None
    lastSeen: str | None = None
    txHashes: list[str] = []
    explorerUrls: list[str] = []
    risk: dict[str, Any] | None = None
    relevance: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = []
    flags: list[str] = []


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    animated: bool = False
    data: GraphEdgeData


class Graph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class TraceStats(BaseModel):
    edgesTraced: int
    addressesDiscovered: int
    nodes: int
    graphEdges: int
    totalValueUsd: float
    walletsPersisted: int = 0
    transactionsPersisted: int = 0
    scored: int = 0
    scoringMode: Literal["heuristic", "ml+heuristic", "rules_only", "none"] = "none"
    # complete=False means at least one address on the frontier could not be
    # read, so the graph is a SUBSET of the real one. Reporting it is what
    # lets a differing node count be explained instead of guessed at.
    complete: bool = True
    addressesUnreachable: int = 0
    upstreamRequests: int = 0
    upstreamCacheHits: int = 0
    rateLimitRetries: int = 0


class TraceResponse(BaseModel):
    ok: bool = True
    dataSource: Literal["live"] = "live"
    targets: list[Target]
    hops: int
    chains: list[str]
    stats: TraceStats
    prices: dict[str, Any]
    providerErrors: list[str] = []
    graph: Graph
    transactions: list[dict[str, Any]] = []
    elapsedMs: int


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str
    environment: str
    time: str
    checks: dict[str, Any]
