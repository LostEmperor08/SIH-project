"""
Unit & Integration Test Suite for Batch 5 Monitored Wallet Surveillance & Cursors.
"""
from __future__ import annotations

import pytest
from app.services.monitoring import (
    MonitoringService,
    MonitoredTarget,
    STATE_ACTIVE,
    STATE_DEGRADED,
    MONITORING_ENGINE_VERSION,
    get_monitoring_service,
)


def test_monitoring_service_initialization():
    """MonitoringService initializes with correct version and chain status."""
    svc = get_monitoring_service()
    status = svc.status()
    assert status["engine_version"] == "5.0.0"
    assert status["running"] is False
    assert "eth" in status["chain_status"]
    assert "polygon" in status["chain_status"]


@pytest.mark.anyio
async def test_monitoring_service_start_stop():
    """MonitoringService starts and stops cleanly in background."""
    svc = get_monitoring_service()
    await svc.start()
    assert svc.is_running is True
    await svc.stop()
    assert svc.is_running is False


def test_monitored_target_dataclass():
    """MonitoredTarget dataclass structures case isolation & mode attributes correctly."""
    target = MonitoredTarget(
        id="target-1",
        case_id="SIH/2026/00412",
        chain="polygon",
        address="0xmonitored123",
        label="Target Mule",
        enabled=True,
        monitoring_mode="CONTINUOUS",
        last_processed_block=100050,
        last_processed_timestamp="2026-03-31T10:00:00Z",
        created_by="Officer Sharma",
        created_at="2026-03-31T10:00:00Z",
        updated_at="2026-03-31T10:00:00Z",
    )
    assert target.case_id == "SIH/2026/00412"
    assert target.chain == "polygon"
    assert target.enabled is True
    assert target.monitoring_mode == "CONTINUOUS"
