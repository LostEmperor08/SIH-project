"""
SAHYOG Platform Integration Adapter (Batch 7).

Provides outbound integration boundary for official interstate law-enforcement action requests.
Operates in SIMULATION mode unless live government credentials are configured.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from ..evidence_provenance import canonical_json, sha256_hex

log = logging.getLogger("chakravyuh.integrations.sahyog")

SAHYOG_ADAPTER_VERSION = "7.0.0"

# Mode: SIMULATION | CONNECTED | NOT_CONFIGURED
SAHYOG_MODE = os.environ.get("SAHYOG_INTEGRATION_MODE", "SIMULATION")

_IN_MEMORY_SAHYOG_LOG: list[dict[str, Any]] = []


class SAHYOGAdapter:
    """SAHYOG Integration Adapter."""

    def __init__(self):
        self._mode = SAHYOG_MODE

    def get_status(self) -> dict[str, Any]:
        return {
            "integration": "SAHYOG",
            "mode": self._mode,
            "active": True,
            "description": "SAHYOG Inter-State Coordination Integration Boundary — Simulation Mode Active.",
        }

    def submit_action_request(
        self,
        case_id: str,
        action_type: str,
        target_wallet: str,
        target_vasp: str | None = None,
        created_by: str = "Officer User",
    ) -> dict[str, Any]:
        """
        Submits an official action request (e.g. PRESERVATION_REQUEST) to SAHYOG platform.
        Uses idempotency key to prevent duplicate official submissions.
        """
        snapshot_bytes = f"{case_id}:{action_type}:{target_wallet}"
        idempotency_key = sha256_hex(snapshot_bytes)[:32]

        # Check existing idempotency
        for existing in _IN_MEMORY_SAHYOG_LOG:
            if existing["idempotency_key"] == idempotency_key:
                log.info("Idempotent SAHYOG action retry returned existing action record.")
                return existing

        now = datetime.now(timezone.utc).isoformat()
        action_id = f"sahyog-{uuid.uuid4().hex[:8]}"
        ext_ref = f"SAHYOG-SIM-2026-{uuid.uuid4().hex[:6].upper()}"

        payload = {
            "case_id": case_id,
            "action_type": action_type,
            "target_wallet": target_wallet,
            "target_vasp": target_vasp,
            "requested_by": created_by,
            "requested_at": now,
        }
        payload_hash = sha256_hex(canonical_json(payload))

        response_payload = {
            "sahyog_ticket_id": ext_ref,
            "action_type": action_type,
            "status": "SIMULATION_SUCCESS",
            "message": f"{action_type} recorded in SAHYOG coordination simulation queue.",
            "acknowledged_at": now,
        }
        response_hash = sha256_hex(canonical_json(response_payload))

        action_record = {
            "id": action_id,
            "case_id": case_id,
            "integration": "SAHYOG",
            "action_type": action_type,
            "idempotency_key": idempotency_key,
            "status": "SIMULATION",
            "external_reference": ext_ref,
            "payload_hash": payload_hash,
            "response_hash": response_hash,
            "response_payload": response_payload,
            "simulated": True,
            "created_by": created_by,
            "created_at": now,
        }
        _IN_MEMORY_SAHYOG_LOG.append(action_record)
        return action_record


_SAHYOG_ADAPTER_INSTANCE = SAHYOGAdapter()


def get_sahyog_adapter() -> SAHYOGAdapter:
    return _SAHYOG_ADAPTER_INSTANCE
