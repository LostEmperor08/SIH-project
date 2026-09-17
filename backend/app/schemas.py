"""
Pydantic request/response models — Control 5: strict validation.

Every address is regex-checked against its chain BEFORE any network call.
That is both a correctness measure (no wasted provider quota on typos) and a
security one: these strings end up in upstream URLs, so unvalidated input is
a path-traversal and SSRF vector.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    model_config = ConfigDict(extra="allow")

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
    sanctionSource: str | None = None
    structuredAlertEvents: list[dict[str, Any]] = []
    scoringMode: str | None = None
    riskEngineVersion: str | None = None
    mlModelVersion: str | None = None
    mlFeatureVersion: str | None = None
    transactionAggregates: dict[str, Any] = {}
    narrative: str | None = None
    typologies: list[Any] = []
    recommendedActions: list[str] = []
    factors: list[Any] = []
    explanation: list[Any] = []
    evidence: list[Any] = []
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
    model_config = ConfigDict(extra="allow")

    id: str
    type: str = "wallet"
    data: GraphNodeData


class GraphEdgeData(BaseModel):
    model_config = ConfigDict(extra="allow")

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
    isBridge: bool = False
    bridgeInfo: dict[str, Any] | None = None


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

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
    crossChainTransfers: list[dict[str, Any]] = []
    crossChain: dict[str, Any] | None = None
    nearestExchange: dict[str, Any] | None = None
    attribution: dict[str, Any] | None = None
    elapsedMs: int


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str
    environment: str
    time: str
    checks: dict[str, Any]


class ReadinessResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    service: str
    version: str
    timestamp: str
    database: str
    ml_status: str
    monitoring_status: str
    providers: dict[str, str]



# =====================================================================
# Batch 5: Monitored Wallets & Streaming Alerts Schemas
# =====================================================================
class MonitoredWalletCreate(BaseModel):
    case_id: str = Field(default="SIH/2026/00412", max_length=100)
    chain: str = Field(min_length=2, max_length=20)
    address: str = Field(min_length=10, max_length=128)
    label: str | None = Field(default=None, max_length=200)
    monitoring_mode: Literal["CONTINUOUS", "POLLING", "MANUAL_REFRESH"] = "CONTINUOUS"


class MonitoredWalletResponse(BaseModel):
    id: str
    case_id: str
    chain: str
    address: str
    label: str | None = None
    enabled: bool = True
    monitoring_mode: str = "CONTINUOUS"
    last_processed_block: int | None = None
    last_processed_timestamp: str | None = None
    created_by: str | None = None
    created_at: str
    updated_at: str


class AlertActionRequest(BaseModel):
    action: Literal["ACKNOWLEDGE", "RESOLVE", "DISMISS"]
    reason: str | None = Field(default=None, max_length=1000)


class AlertResponse(BaseModel):
    id: str
    case_id: str
    monitored_wallet_id: str | None = None
    chain: str
    tx_hash: str
    idempotency_key: str
    alert_type: str
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    title: str
    summary: str
    risk_score: float | None = None
    relevance_score: float | None = None
    attributed_value_usd: float = 0.0
    attribution_share: float = 0.0
    vasp_name: str | None = None
    vasp_confidence: float | None = None
    bridge_name: str | None = None
    bridge_confidence: float | None = None
    evidence: list[Any] = []
    triggered_rules: list[Any] = []
    status: Literal["NEW", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED"] = "NEW"
    suppressed: bool = False
    created_at: str
    acknowledged_at: str | None = None
    resolved_at: str | None = None


# =====================================================================
# Batch 6: Investigator Case Workspace Schemas
# =====================================================================
class CaseCreate(BaseModel):
    case_ref: str = Field(default_factory=lambda: f"SIH/2026/{hashlib.sha256(str(datetime.now().timestamp()).encode()).hexdigest()[:5].upper()}", max_length=100)
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    reported_wallet: str = Field(min_length=10, max_length=128)
    reported_chain: str = Field(default="polygon", max_length=20)
    reported_amount_usd: float = Field(default=0.0, ge=0.0)
    priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"] = "HIGH"
    org_unit: str | None = "Cyber Crime PS · I4C Operations"


class CaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"] | None = None
    assigned_officer_id: str | None = None


class CaseStatusUpdate(BaseModel):
    status: Literal["OPEN", "ACTIVE", "UNDER_REVIEW", "PENDING_ACTION", "CLOSED", "ARCHIVED"]
    note: str | None = Field(default=None, max_length=1000)


class CaseResponse(BaseModel):
    id: str
    case_ref: str
    title: str
    description: str | None = None
    reported_wallet: str
    reported_chain: str
    reported_amount_usd: float
    status: Literal["OPEN", "ACTIVE", "UNDER_REVIEW", "PENDING_ACTION", "CLOSED", "ARCHIVED"]
    priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"]
    assigned_officer_id: str | None = None
    org_unit: str | None = None
    created_by: str | None = None
    created_at: str
    updated_at: str


class CaseNoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    is_pinned: bool = False


class CaseNoteResponse(BaseModel):
    id: str
    case_id: str
    author_id: str
    author_name: str
    text: str
    is_pinned: bool
    created_at: str
    updated_at: str


class CaseTaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    assignee: str | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    due_at: str | None = None


class CaseTaskResponse(BaseModel):
    id: str
    case_id: str
    title: str
    description: str | None = None
    assignee: str | None = None
    status: Literal["PENDING", "IN_PROGRESS", "COMPLETED"]
    priority: Literal["LOW", "MEDIUM", "HIGH"]
    due_at: str | None = None
    created_by: str
    created_at: str
    updated_at: str


class RecommendationItem(BaseModel):
    id: str
    priority: Literal["INFO", "LOW", "MEDIUM", "HIGH"]
    title: str
    action_text: str
    basis: list[str]
    target_wallet: str | None = None
    target_tx_hash: str | None = None
    target_vasp: str | None = None


class TimelineItem(BaseModel):
    id: str
    case_id: str
    event_type: str
    title: str
    description: str | None = None
    actor: str
    actor_role: str = "INVESTIGATOR"
    metadata: dict[str, Any] = {}
    created_at: str


# =====================================================================
# Batch 7: Evidence Provenance, Reports & Government Integrations
# =====================================================================
class EvidenceRecordCreate(BaseModel):
    case_id: str = Field(default="SIH/2026/00412", max_length=100)
    classification: Literal["OBSERVED", "DERIVED", "EXTERNAL_INTELLIGENCE", "INVESTIGATOR_CREATED", "SYSTEM_GENERATED"] = "OBSERVED"
    evidence_type: Literal["BLOCKCHAIN_TRANSACTION", "BLOCKCHAIN_TRANSFER", "WALLET_ACTIVITY", "VASP_IDENTIFICATION", "BRIDGE_CORRELATION", "RISK_ASSESSMENT", "ML_ASSESSMENT", "SANCTIONS_MATCH", "ALERT_EVENT", "INVESTIGATOR_NOTE", "REPORT", "NOTICE"] = "BLOCKCHAIN_TRANSACTION"
    chain: str = Field(default="polygon", max_length=20)
    address: str | None = None
    tx_hash: str | None = None
    block_number: int | None = None
    source_provider: str = "Chakravyuh Provider Network"
    source_endpoint: str | None = None
    payload: dict[str, Any] = {}


class EvidenceRecordResponse(BaseModel):
    id: str
    case_id: str
    case_ref: str
    classification: Literal["OBSERVED", "DERIVED", "EXTERNAL_INTELLIGENCE", "INVESTIGATOR_CREATED", "SYSTEM_GENERATED"]
    evidence_type: str
    chain: str
    address: str | None = None
    tx_hash: str | None = None
    block_number: int | None = None
    source_provider: str
    source_endpoint: str | None = None
    retrieved_at: str
    observed_at: str
    raw_payload_hash: str | None = None
    normalized_payload_hash: str
    prev_hash: str | None = None
    chain_hash: str
    status: Literal["COLLECTED", "VERIFIED", "SEALED", "SUPERSEDED", "INVALIDATED"]
    engine_versions: dict[str, Any] = {}
    created_by: str
    created_at: str


class EvidenceVerificationResponse(BaseModel):
    record_id: str | None = None
    case_id: str | None = None
    total_records: int = 0
    verified_records: int = 0
    tampered_records: int = 0
    verdict: Literal["INTACT", "TAMPERED"]
    details: list[dict[str, Any]] = []


class ReportGenerateRequest(BaseModel):
    include_raw_payloads: bool = False
    custom_notes: str | None = Field(default=None, max_length=2000)


class ReportResponse(BaseModel):
    id: str
    case_id: str
    case_ref: str
    report_version: str
    pdf_hash: str
    html_content: str | None = None
    pdf_path: str | None = None
    report_metadata: dict[str, Any] = {}
    engine_versions: dict[str, Any] = {}
    created_by: str
    created_at: str


class NoticeGenerateRequest(BaseModel):
    recipient_vasp: str = Field(min_length=2, max_length=200)
    target_address: str = Field(min_length=10, max_length=128)
    legal_jurisdiction: str = Field(default="BNSS / Section 91 CrPC, India", max_length=200)


class NoticeResponse(BaseModel):
    case_id: str
    case_ref: str
    recipient_vasp: str
    target_address: str
    notice_text: str
    generated_at: str
    jurisdiction: str


class IntegrationStatusResponse(BaseModel):
    ncrp_mode: Literal["NOT_CONFIGURED", "SIMULATION", "CONNECTED", "SUBMITTED"]
    sahyog_mode: Literal["NOT_CONFIGURED", "SIMULATION", "CONNECTED", "SUBMITTED"]
    ncrp_active: bool
    sahyog_active: bool
    description: str


class NCRPSubmitRequest(BaseModel):
    case_id: str = Field(default="SIH/2026/00412")
    submit_report: bool = True
    custom_reference: str | None = None


class SahyogSubmitRequest(BaseModel):
    case_id: str = Field(default="SIH/2026/00412")
    action_type: Literal["PRESERVATION_REQUEST", "INFORMATION_REQUEST", "TRANSACTION_REVIEW_REQUEST", "ACCOUNT_IDENTIFICATION_REQUEST"] = "PRESERVATION_REQUEST"
    target_wallet: str = Field(min_length=10, max_length=128)
    target_vasp: str | None = None


class IntegrationActionResponse(BaseModel):
    id: str
    case_id: str
    integration: Literal["NCRP", "SAHYOG"]
    action_type: str
    idempotency_key: str
    status: Literal["NOT_CONFIGURED", "SIMULATION", "CONNECTED", "SUBMITTED", "FAILED"]
    external_reference: str
    payload_hash: str
    response_hash: str
    simulated: bool = True
    created_at: str



