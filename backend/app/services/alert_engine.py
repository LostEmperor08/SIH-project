"""
Alert Engine — Rules evaluation, deterministic severity, idempotency deduplication,
alert lifecycle management, and WebSocket live broadcasting (Batch 5).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("chakravyuh.alert_engine")

ALERT_ENGINE_VERSION = "5.0.0"

# Alert Severities
SEVERITY_INFO = "INFO"
SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"

# Alert Types
TYPE_SANCTIONS = "SANCTIONS_MATCH"
TYPE_CRITICAL_TX = "CRITICAL_TRANSACTION"
TYPE_HIGH_RISK_TX = "HIGH_RISK_TRANSACTION"
TYPE_LARGE_FUND = "LARGE_REPORTED_FUND_MOVEMENT"
TYPE_KNOWN_EXCHANGE = "KNOWN_EXCHANGE_REACHED"
TYPE_CROSS_CHAIN = "CROSS_CHAIN_MOVEMENT"
TYPE_BRIDGE_CORRELATION = "BRIDGE_CORRELATION"
TYPE_RAPID_FORWARDING = "RAPID_FUND_FORWARDING"
TYPE_NEW_COUNTERPARTY = "NEW_HIGH_RISK_COUNTERPARTY"
TYPE_MIXER = "MIXER_INTERACTION"
TYPE_STRUCTURING = "STRUCTURING_PATTERN"
TYPE_SUDDEN_ACTIVITY = "SUDDEN_WALLET_ACTIVITY"

# Alert Lifecycle Statuses
STATUS_NEW = "NEW"
STATUS_ACKNOWLEDGED = "ACKNOWLEDGED"
STATUS_INVESTIGATING = "INVESTIGATING"
STATUS_RESOLVED = "RESOLVED"
STATUS_DISMISSED = "DISMISSED"


def generate_idempotency_key(
    case_id: str, chain: str, tx_hash: str, alert_type: str, rule_id: str
) -> str:
    """Generate deterministic idempotency key to prevent duplicate alerts."""
    raw = f"{case_id}:{chain.lower()}:{tx_hash.lower()}:{alert_type}:{rule_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass
class AlertCandidate:
    case_id: str
    monitored_wallet_id: str | None
    chain: str
    tx_hash: str
    rule_id: str
    alert_type: str
    severity: str
    title: str
    summary: str
    risk_score: float
    relevance_score: float
    attributed_value_usd: float
    attribution_share: float
    vasp_name: str | None = None
    vasp_confidence: float | None = None
    bridge_name: str | None = None
    bridge_confidence: float | None = None
    evidence: list[str] = field(default_factory=list)
    triggered_rules: list[str] = field(default_factory=list)

    @property
    def idempotency_key(self) -> str:
        return generate_idempotency_key(
            self.case_id, self.chain, self.tx_hash, self.alert_type, self.rule_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "monitored_wallet_id": self.monitored_wallet_id,
            "chain": self.chain,
            "tx_hash": self.tx_hash,
            "idempotency_key": self.idempotency_key,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "title": self.title,
            "summary": self.summary,
            "risk_score": round(self.risk_score, 2),
            "relevance_score": round(self.relevance_score, 2),
            "attributed_value_usd": round(self.attributed_value_usd, 2),
            "attribution_share": round(self.attribution_share, 4),
            "vasp_name": self.vasp_name,
            "vasp_confidence": round(self.vasp_confidence, 4) if self.vasp_confidence else None,
            "bridge_name": self.bridge_name,
            "bridge_confidence": round(self.bridge_confidence, 4) if self.bridge_confidence else None,
            "evidence": self.evidence,
            "triggered_rules": self.triggered_rules,
            "status": STATUS_NEW,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


class AlertBroadcaster:
    """In-memory WebSocket Connection Hub for live streaming alerts."""

    def __init__(self):
        self._active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._active_connections.append(websocket)
        log.info("WebSocket client connected. Total active: %d", len(self._active_connections))

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._active_connections:
                self._active_connections.remove(websocket)
        log.info("WebSocket client disconnected.")

    async def broadcast(self, payload: dict[str, Any]):
        async with self._lock:
            dead: list[WebSocket] = []
            for ws in self._active_connections:
                try:
                    await ws.send_json(payload)
                except Exception as e:
                    log.warning("WebSocket send failed: %s", e)
                    dead.append(ws)
            for ws in dead:
                if ws in self._active_connections:
                    self._active_connections.remove(ws)


BROADCASTER = AlertBroadcaster()


def evaluate_alert_rules(
    tx_context: dict[str, Any],
    wallet_context: dict[str, Any] | None = None,
    case_id: str = "SIH/2026/00412",
    monitored_wallet_id: str | None = None,
) -> list[AlertCandidate]:
    """
    Evaluates transaction & wallet analytical context through explicit rules.
    Returns a list of alert candidates.
    """
    tx_context = tx_context or {}
    wallet_context = wallet_context or {}

    tx_hash = tx_context.get("tx_hash") or "0xhash"
    chain = tx_context.get("chain") or "polygon"
    risk_obj = tx_context.get("risk") or {}
    rel_obj = tx_context.get("relevance") or {}

    risk_score = float(risk_obj.get("score") or 0.0)
    relevance_score = float(rel_obj.get("score") or 0.0)
    attr_usd = float(rel_obj.get("attributed_value_usd") or 0.0)
    attr_share = float(rel_obj.get("fund_attribution_share") or rel_obj.get("taint_share") or 0.0)

    factors = risk_obj.get("factors") or []
    factor_codes = {f.get("code") for f in factors if isinstance(f, dict)}

    vasp_attr = wallet_context.get("vasp_attribution") or tx_context.get("vasp_attribution")
    bridge_info = tx_context.get("bridge_info") or tx_context.get("cross_chain_transfer")

    candidates: list[AlertCandidate] = []

    # 1. Sanctions Match Rule
    is_sanctions = risk_obj.get("sanction_floor_applied") or "SANCTIONS_EXPOSURE" in factor_codes or wallet_context.get("sanction_floor_applied")
    if is_sanctions:
        candidates.append(AlertCandidate(
            case_id=case_id,
            monitored_wallet_id=monitored_wallet_id,
            chain=chain,
            tx_hash=tx_hash,
            rule_id="RULE_SANCTIONS",
            alert_type=TYPE_SANCTIONS,
            severity=SEVERITY_CRITICAL,
            title="CRITICAL — Verified Sanctions Match",
            summary=f"Transaction directly involves an OFAC SDN sanctioned entity on {chain.upper()}.",
            risk_score=max(risk_score, 90.0),
            relevance_score=relevance_score,
            attributed_value_usd=attr_usd,
            attribution_share=attr_share,
            evidence=["Verified OFAC SDN sanctions match", "Direct regulatory enforcement mandatory"],
            triggered_rules=["RULE_SANCTIONS"],
        ))

    # 2. Critical Risk Transaction Rule
    if risk_score >= 80.0 and not is_sanctions:
        candidates.append(AlertCandidate(
            case_id=case_id,
            monitored_wallet_id=monitored_wallet_id,
            chain=chain,
            tx_hash=tx_hash,
            rule_id="RULE_CRITICAL_RISK",
            alert_type=TYPE_CRITICAL_TX,
            severity=SEVERITY_CRITICAL,
            title="CRITICAL — High Composite Risk Transfer",
            summary=f"Transaction scored {risk_score:.1f}/100 (CRITICAL) on {chain.upper()}.",
            risk_score=risk_score,
            relevance_score=relevance_score,
            attributed_value_usd=attr_usd,
            attribution_share=attr_share,
            evidence=[f.get("evidence", "") for f in factors[:3]],
            triggered_rules=["RULE_CRITICAL_RISK"],
        ))

    # 3. High Risk Transaction Rule
    elif risk_score >= 60.0 and not is_sanctions:
        candidates.append(AlertCandidate(
            case_id=case_id,
            monitored_wallet_id=monitored_wallet_id,
            chain=chain,
            tx_hash=tx_hash,
            rule_id="RULE_HIGH_RISK",
            alert_type=TYPE_HIGH_RISK_TX,
            severity=SEVERITY_HIGH,
            title="HIGH — Elevated Risk Transfer",
            summary=f"Transaction scored {risk_score:.1f}/100 (HIGH) on {chain.upper()}.",
            risk_score=risk_score,
            relevance_score=relevance_score,
            attributed_value_usd=attr_usd,
            attribution_share=attr_share,
            evidence=[f.get("evidence", "") for f in factors[:2]],
            triggered_rules=["RULE_HIGH_RISK"],
        ))

    # 4. Large Reported Fund Movement Rule
    if attr_usd >= 1000.0 or attr_share >= 0.50:
        candidates.append(AlertCandidate(
            case_id=case_id,
            monitored_wallet_id=monitored_wallet_id,
            chain=chain,
            tx_hash=tx_hash,
            rule_id="RULE_LARGE_ATTRIBUTED_FUND",
            alert_type=TYPE_LARGE_FUND,
            severity=SEVERITY_HIGH if attr_usd >= 5000.0 else SEVERITY_MEDIUM,
            title="HIGH — Reported Victim Funds Moved",
            summary=f"${attr_usd:,.2f} ({attr_share:.1%}) of victim reported funds transferred on {chain.upper()}.",
            risk_score=risk_score,
            relevance_score=relevance_score,
            attributed_value_usd=attr_usd,
            attribution_share=attr_share,
            evidence=[f"Carries ${attr_usd:,.2f} of victim complaint funds", f"Fund attribution share: {attr_share:.1%}"],
            triggered_rules=["RULE_LARGE_ATTRIBUTED_FUND"],
        ))

    # 5. Rapid Fund Forwarding Rule
    if "RAPID_PASS_THROUGH" in factor_codes or "FAST_FORWARDING" in factor_codes:
        candidates.append(AlertCandidate(
            case_id=case_id,
            monitored_wallet_id=monitored_wallet_id,
            chain=chain,
            tx_hash=tx_hash,
            rule_id="RULE_RAPID_FORWARDING",
            alert_type=TYPE_RAPID_FORWARDING,
            severity=SEVERITY_HIGH,
            title="HIGH — Rapid Pass-Through Forwarding",
            summary=f"High-velocity money forwarding detected on {chain.upper()}.",
            risk_score=risk_score,
            relevance_score=relevance_score,
            attributed_value_usd=attr_usd,
            attribution_share=attr_share,
            evidence=["Immediate forwarding after receipt", "Layering mule signature"],
            triggered_rules=["RULE_RAPID_FORWARDING"],
        ))

    # 6. Known Exchange Reached Rule (INFO/LOW unless high risk)
    if vasp_attr and vasp_attr.get("identified") is not False:
        v_name = vasp_attr.get("name") or vasp_attr.get("exchange_name") or "Verified VASP"
        v_conf = float(vasp_attr.get("confidence") or 0.85)
        candidates.append(AlertCandidate(
            case_id=case_id,
            monitored_wallet_id=monitored_wallet_id,
            chain=chain,
            tx_hash=tx_hash,
            rule_id="RULE_KNOWN_EXCHANGE",
            alert_type=TYPE_KNOWN_EXCHANGE,
            severity=SEVERITY_INFO if risk_score < 60.0 else SEVERITY_HIGH,
            title=f"INFO — Exchange Deposit Reached: {v_name}",
            summary=f"Funds deposited into {v_name} with {v_conf:.0%} confidence.",
            risk_score=risk_score,
            relevance_score=relevance_score,
            attributed_value_usd=attr_usd,
            attribution_share=attr_share,
            vasp_name=v_name,
            vasp_confidence=v_conf,
            evidence=[f"VASP: {v_name}", f"Confidence: {v_conf:.0%}", "Prepare Section 91 BNSS freeze notice"],
            triggered_rules=["RULE_KNOWN_EXCHANGE"],
        ))

    # 7. Cross-Chain Bridge Correlation Rule
    if bridge_info:
        b_name = bridge_info.get("bridge_name") or bridge_info.get("name") or "Cross-Chain Bridge"
        b_conf = float(bridge_info.get("correlation_confidence") or bridge_info.get("confidence") or 0.90)
        candidates.append(AlertCandidate(
            case_id=case_id,
            monitored_wallet_id=monitored_wallet_id,
            chain=chain,
            tx_hash=tx_hash,
            rule_id="RULE_CROSS_CHAIN_BRIDGE",
            alert_type=TYPE_CROSS_CHAIN,
            severity=SEVERITY_MEDIUM,
            title=f"MEDIUM — Cross-Chain Transfer ({b_name})",
            summary=f"Cross-chain bridge transition correlated via {b_name} ({b_conf:.0%} confidence).",
            risk_score=risk_score,
            relevance_score=relevance_score,
            attributed_value_usd=attr_usd,
            attribution_share=attr_share,
            bridge_name=b_name,
            bridge_confidence=b_conf,
            evidence=[f"Bridge Protocol: {b_name}", f"Correlation confidence: {b_conf:.0%}"],
            triggered_rules=["RULE_CROSS_CHAIN_BRIDGE"],
        ))

    return candidates
