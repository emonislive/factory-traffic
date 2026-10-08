"""Tests for async repositories.

Verifies persistence, schema integrity, and append-only audit log rules.
Owned by Agent B (Phase 1).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.db.models import Base, JunctionStateModel
from app.infrastructure.db.repositories import (
    AuditLogRepository,
    CommandRepository,
    DeviceStatusRepository,
    DirectionSequenceRepository,
    JunctionRepository,
    ProcessedEventRepository,
    VehicleRepository,
)


@pytest.fixture
async def async_test_session() -> AsyncGenerator[AsyncSession, None]:
    """Create in-memory SQLite engine and session for repository unit testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_junction_repository_crud(async_test_session: AsyncSession) -> None:
    repo = JunctionRepository(async_test_session)
    # Create
    config = {"phases": {"NS": ["NORTH", "SOUTH"], "EW": ["EAST", "WEST"]}}
    junction = await repo.create("J1", "Junction One", config)
    assert junction.id == "J1"

    # Get
    fetched = await repo.get("J1")
    assert fetched is not None
    assert fetched.name == "Junction One"

    # List
    all_j = await repo.list_all()
    assert len(all_j) == 1
    assert all_j[0].id == "J1"

    # Save state
    state = JunctionStateModel(
        junction_id="J1",
        version=1,
        mode="AUTOMATIC",
        serving="NS",
        step="GREEN",
        target=None,
        deadline_at=100.0,
        desired={"NORTH": "GREEN"},
        actual={"NORTH": "GREEN"},
        manual={"active": False},
        emergencies=[],
    )
    saved_state = await repo.save_state(state)
    assert saved_state.version == 1

    # Update state
    state.version = 2
    state.step = "YELLOW"
    updated_state = await repo.save_state(state)
    assert updated_state.version == 2
    assert updated_state.step == "YELLOW"


@pytest.mark.asyncio
async def test_vehicle_repository_arrival_and_clearance(
    async_test_session: AsyncSession,
) -> None:
    # Setup junction
    j_repo = JunctionRepository(async_test_session)
    await j_repo.create("J1", "J1", {})

    v_repo = VehicleRepository(async_test_session)
    # 1. Normal arrival
    v1 = await v_repo.record_arrival(
        junction_id="J1",
        vehicle_id="V-100",
        direction="NORTH",
        vehicle_type="TRUCK",
        sequence_no=1,
        sensor_time=datetime.now(UTC),
        server_time=100.0,
    )
    assert v1 is not None
    assert v1.status == "WAITING"

    # 2. Duplicate arrival for same vehicle while WAITING is idempotent
    v1_dup = await v_repo.record_arrival(
        junction_id="J1",
        vehicle_id="V-100",
        direction="NORTH",
        vehicle_type="TRUCK",
        sequence_no=2,
        sensor_time=datetime.now(UTC),
        server_time=101.0,
    )
    assert v1_dup is None

    # Queue counts
    counts = await v_repo.get_queue_counts("J1")
    assert counts["NORTH"] == 1
    assert counts["SOUTH"] == 0

    # 3. Clearance
    was_waiting, cleared = await v_repo.record_clearance(
        junction_id="J1",
        vehicle_id="V-100",
        direction="NORTH",
        sequence_no=3,
        server_time=105.0,
    )
    assert was_waiting is True
    assert cleared.status == "CLEARED"

    counts_after = await v_repo.get_queue_counts("J1")
    assert counts_after["NORTH"] == 0

    # 4. Orphan clearance (D-13, P-01)
    was_waiting_orphan, orphan = await v_repo.record_clearance(
        junction_id="J1",
        vehicle_id="V-999",
        direction="EAST",
        sequence_no=10,
        server_time=110.0,
    )
    assert was_waiting_orphan is False
    assert orphan.status == "ORPHAN_CLEARED"


@pytest.mark.asyncio
async def test_processed_event_repository(async_test_session: AsyncSession) -> None:
    j_repo = JunctionRepository(async_test_session)
    await j_repo.create("J1", "J1", {})

    p_repo = ProcessedEventRepository(async_test_session)
    ev = await p_repo.record("evt-001", "J1", "APPLIED", {"foo": "bar"})
    assert ev.event_id == "evt-001"

    found = await p_repo.get("evt-001")
    assert found is not None
    assert found.outcome == "APPLIED"

    not_found = await p_repo.get("evt-nonexistent")
    assert not_found is None


@pytest.mark.asyncio
async def test_direction_sequence_repository(async_test_session: AsyncSession) -> None:
    j_repo = JunctionRepository(async_test_session)
    await j_repo.create("J1", "J1", {})

    seq_repo = DirectionSequenceRepository(async_test_session)
    assert await seq_repo.get_last_sequence("J1", "NORTH") == 0

    await seq_repo.update_sequence("J1", "NORTH", 42)
    assert await seq_repo.get_last_sequence("J1", "NORTH") == 42

    # Sequence should not regress
    await seq_repo.update_sequence("J1", "NORTH", 10)
    assert await seq_repo.get_last_sequence("J1", "NORTH") == 42


@pytest.mark.asyncio
async def test_command_repository(async_test_session: AsyncSession) -> None:
    j_repo = JunctionRepository(async_test_session)
    await j_repo.create("J1", "J1", {})

    c_repo = CommandRepository(async_test_session)
    cmd = await c_repo.record_command("cmd-01", "J1", "NORTH", "YELLOW", 100.0, 103.0)
    assert cmd.status == "PENDING"
    assert cmd.attempts == 1

    # Retry
    retried = await c_repo.record_retry("cmd-01", 106.0)
    assert retried is not None
    assert retried.attempts == 2
    assert retried.deadline_at == 106.0

    # ACK
    acked = await c_repo.record_ack("cmd-01", 104.0, "YELLOW")
    assert acked is not None
    assert acked.status == "ACKED"
    assert acked.actual_state == "YELLOW"

    # Abandon pending
    await c_repo.record_command("cmd-02", "J1", "SOUTH", "RED", 100.0, 103.0)
    abandoned_count = await c_repo.abandon_pending("J1")
    assert abandoned_count == 1
    cmd_02 = await c_repo.get("cmd-02")
    assert cmd_02 is not None
    assert cmd_02.status == "ABANDONED"


@pytest.mark.asyncio
async def test_device_status_repository(async_test_session: AsyncSession) -> None:
    j_repo = JunctionRepository(async_test_session)
    await j_repo.create("J1", "J1", {})

    d_repo = DeviceStatusRepository(async_test_session)
    dev = await d_repo.update_status("J1", "SIGNAL_CONTROLLER", "", "ONLINE")
    assert dev.status == "ONLINE"

    all_devs = await d_repo.get_for_junction("J1")
    assert len(all_devs) == 1
    assert all_devs[0].status == "ONLINE"


@pytest.mark.asyncio
async def test_audit_log_is_append_only(async_test_session: AsyncSession) -> None:
    """Verify audit_log repository strictly enforces append-only semantics (Instruction.md 5.4)."""
    j_repo = JunctionRepository(async_test_session)
    await j_repo.create("J1", "J1", {})

    audit_repo = AuditLogRepository(async_test_session)

    # 1. Structural check: No update or delete methods exist on repository class
    assert not hasattr(audit_repo, "update")
    assert not hasattr(audit_repo, "delete")
    assert not hasattr(audit_repo, "remove")
    assert not hasattr(audit_repo, "clear")

    # 2. Append entries
    e1 = await audit_repo.append(
        junction_id="J1",
        event_type="SIGNAL_CHANGED",
        direction="NORTH",
        previous_state="RED",
        new_state="GREEN",
        command_id="cmd-1",
        reason="Scheduled transition",
    )
    assert e1.id is not None

    e2 = await audit_repo.append(
        junction_id="J1",
        event_type="EMERGENCY_DETECTED",
        direction="EAST",
        reason="Priority override",
    )
    assert e2.id is not None

    # 3. Listing with limit and event_type filters
    entries = await audit_repo.list_by_junction("J1")
    assert len(entries) == 2
    # Ordered by id desc
    assert entries[0].event_type == "EMERGENCY_DETECTED"
    assert entries[1].event_type == "SIGNAL_CHANGED"

    filtered = await audit_repo.list_by_junction("J1", event_type="EMERGENCY_DETECTED")
    assert len(filtered) == 1
    assert filtered[0].event_type == "EMERGENCY_DETECTED"
