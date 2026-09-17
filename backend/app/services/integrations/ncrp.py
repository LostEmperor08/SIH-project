"""
NCRP (National Cyber Crime Reporting Portal) Integration Adapter (Batch 7).

Provides outbound integration boundary for NCRP case/report submission.
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

log = logging.getLogger("chakravyuh.integrations.ncrp")

NCRP_ADAPTER_VERSION = "7.0.0"

# Mode: SIMULATION | CONNECTED | NOT_CONFIGURED
NCRP_MODE = os.environ.get("NCRP_INTEGRATION_MODE", "SIMULATION")

_IN_MEMORY_NCRP_LOG: list[dict[str, Any]] = []


class NCRPAdapter:
    """NCRP Integration Adapter."""

    def __init__(self):
        self._mode = NCRP_MODE

    def get_status(self) -> dict[str, Any]:
        return {
            "integration": "NCRP",
            "mode": self._mode,
            "active": True,
            "description": "NCRP Integration Boundary — Simulation Mode Active (No live API calls executed).",
        }

    def submit_report(
        self, case_id: str, submit_report: bool = True, custom_reference: str | None = None, created_by: str = "Officer User"
    ) -> dict[str, Any]:
        """
        Submits case evidence package to NCRP.
        Uses idempotency key to prevent duplicate official submissions.
        """
        snapshot_bytes = f"{case_id}:NCRP_REPORT:{custom_reference or 'DEFAULT'}"
        idempotency_key = sha256_hex(snapshot_bytes)[:32]

        # Check existing idempotency
        for existing in _IN_MEMORY_NCRP_LOG:
            if existing["idempotency_key"] == idempotency_key:
                log.info("Idempotent NCRP submission retry returned existing action record.")
                return existing

        now = datetime.now(timezone.utc).isoformat()
        action_id = f"ncrp-{uuid.uuid4().hex[:8]}"
        ext_ref = custom_reference or f"NCRP-SIM-2026-{uuid.uuid4().hex[:6].upper()}"

        payload = {
            "case_id": case_id,
            "submit_report": submit_report,
            "external_reference": ext_ref,
            "submitted_by": created_by,
            "submitted_at": now,
        }
        payload_hash = sha256_hex(canonical_json(payload))

        response_payload = {
            "ncrp_reference": ext_ref,
            "status": "SIMULATION_SUCCESS",
            "message": "Report evidence snapshot attached successfully to NCRP simulation record.",
            "acknowledged_at": now,
        }
        response_hash = sha256_hex(canonical_json(response_payload))

        action_record = {
            "id": action_id,
            "case_id": case_id,
            "integration": "NCRP",
            "action_type": "CASE_REPORT_SUBMISSION",
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
        _IN_MEMORY_NCRP_LOG.append(action_record)
        return action_record


_NCRP_ADAPTER_INSTANCE = NCRPAdapter()


def get_ncrp_adapter() -> NCRPAdapter:
    return _NCRP_ADAPTER_INSTANCE
