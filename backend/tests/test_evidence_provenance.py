"""
Unit & Integration Test Suite for Batch 7 Evidence Provenance, Canonical JSON Hashing,
Chain Integrity Verification, Evidence Sealing, and Package Exporter.
"""
from __future__ import annotations

import pytest
from app.services.evidence_provenance import (
    EvidenceProvenanceService,
    canonical_json,
    get_evidence_provenance_service,
    sha256_hex,
    CLASS_DERIVED,
    CLASS_EXTERNAL_INTEL,
    CLASS_OBSERVED,
    STATUS_SEALED,
)


def test_canonical_json_deterministic():
    """Canonical JSON produces stable key ordering regardless of input dictionary key order."""
    dict_a = {"z_key": "val1", "a_key": "val2", "m_key": 100}
    dict_b = {"a_key": "val2", "m_key": 100, "z_key": "val1"}

    json_a = canonical_json(dict_a)
    json_b = canonical_json(dict_b)

    assert json_a == json_b
    assert json_a == '{"a_key":"val2","m_key":100,"z_key":"val1"}'
    assert sha256_hex(json_a) == sha256_hex(json_b)


def test_create_and_seal_evidence_record():
    """Creates a new evidence record and seals it into the cryptographic chain."""
    svc = get_evidence_provenance_service()
    payload = {"tx_hash": "0xabc123", "value_usd": 15000.0, "hop": 1}
    rec = svc.create_evidence_record(
        case_id="SIH/2026/00412",
        classification=CLASS_OBSERVED,
        evidence_type="BLOCKCHAIN_TRANSACTION",
        payload=payload,
        chain="polygon",
        tx_hash="0xabc123",
        created_by="Officer Sharma",
    )

    assert rec["id"].startswith("EV-")
    assert rec["classification"] == CLASS_OBSERVED
    assert rec["status"] == STATUS_SEALED
    assert rec["normalized_payload_hash"] is not None
    assert rec["chain_hash"] is not None


def test_verify_evidence_integrity():
    """Verifies SHA-256 content and chain hash integrity for an evidence record."""
    svc = get_evidence_provenance_service()
    records = svc.get_case_evidence("SIH/2026/00412")
    assert len(records) >= 1

    rec_id = records[0]["id"]
    verification = svc.verify_evidence_integrity(rec_id)

    assert verification["record_id"] == rec_id
    assert verification["verdict"] == "INTACT"
    assert verification["content_ok"] is True
    assert verification["link_ok"] is True


def test_verify_case_evidence_chain():
    """Verifies the complete sequence of evidence hash chains for an investigation case."""
    svc = get_evidence_provenance_service()
    chain_verdict = svc.verify_case_evidence_chain("SIH/2026/00412")

    assert chain_verdict["case_id"] == "SIH/2026/00412"
    assert chain_verdict["total_records"] >= 2
    assert chain_verdict["tampered_records"] == 0
    assert chain_verdict["verdict"] == "INTACT"


def test_build_evidence_package():
    """Builds a machine-readable evidence export package containing manifest.json and per-file hashes."""
    svc = get_evidence_provenance_service()
    pkg = svc.build_evidence_package("SIH/2026/00412")

    assert "manifest" in pkg
    assert "records" in pkg
    manifest = pkg["manifest"]
    assert manifest["case_id"] == "SIH/2026/00412"
    assert manifest["evidence_count"] >= 2
    assert manifest["hash_algorithm"] == "SHA-256"
    assert "package_manifest_hash" in manifest
    assert len(manifest["files"]) >= 2

    # Check secret absence
    manifest_str = canonical_json(manifest)
    assert "api_key" not in manifest_str.lower()
    assert "password" not in manifest_str.lower()
    assert "secret" not in manifest_str.lower()
