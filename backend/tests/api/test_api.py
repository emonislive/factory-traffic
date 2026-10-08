"""API integration tests matching contracts/openapi.yaml and P-02.

Owned by Agent B (Phase 1).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.junction_worker import JunctionWorker, get_junction_manager
from app.domain.types import Direction, JunctionConfig, Phase, TimingsConfig
from app.infrastructure.db.models import Base
from app.infrastructure.db.session import set_engine
from app.main import create_app


@pytest.fixture
async def client_and_manager() -> AsyncGenerator[tuple[AsyncClient, JunctionWorker], None]:
    """Setup in-memory DB and test client with cleanly initialized Junction A."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    set_engine(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    manager = get_junction_manager()
    manager.session_factory = session_factory
    manager._workers.clear()

    # Register Junction A
    config = JunctionConfig(
        id="A",
        name="Junction A",
        phases={
            Phase.NS: [Direction.NORTH, Direction.SOUTH],
            Phase.EW: [Direction.EAST, Direction.WEST],
        },
        timings=TimingsConfig(ack_timeout=3.0, max_retries=2),
    )
    worker = JunctionWorker(
        junction_id="A",
        config=config,
        session_factory=session_factory,
    )
    manager._workers["A"] = worker
    await worker.start()

    async with session_factory() as s:
        async with s.begin():
            from app.infrastructure.db.models import JunctionStateModel
            from app.infrastructure.db.repositories import JunctionRepository

            repo = JunctionRepository(s)
            await repo.create(
                "A",
                "Junction A",
                {
                    "phases": {"NS": ["NORTH", "SOUTH"], "EW": ["EAST", "WEST"]},
                    "timings": {"ack_timeout": 3.0, "max_retries": 2},
                },
            )
            initial_state = JunctionStateModel(
                junction_id="A",
                version=1,
                mode="AUTOMATIC",
                serving="NS",
                step="BOOT",
                target=None,
                deadline_at=None,
                desired={"NORTH": "RED", "SOUTH": "RED", "EAST": "RED", "WEST": "RED"},
                actual={
                    "NORTH": "UNKNOWN",
                    "SOUTH": "UNKNOWN",
                    "EAST": "UNKNOWN",
                    "WEST": "UNKNOWN",
                },
                manual={"active": False},
                emergencies=[],
            )
            await repo.save_state(initial_state)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, worker

    await worker.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_junctions(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, _ = client_and_manager
    response = await client.get("/api/junctions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_create_junction_validation_and_conflict(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, _ = client_and_manager
    # 1. Invalid config (overlapping phases) -> 422
    bad_payload = {
        "id": "B",
        "name": "Junction B",
        "phases": {
            "NS": ["NORTH", "SOUTH"],
            "EW": ["NORTH", "WEST"],  # Overlap on NORTH!
        },
    }
    res = await client.post("/api/junctions", json=bad_payload)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "INVALID_JUNCTION_CONFIG"

    # 2. Valid creation -> 201
    valid_payload = {
        "id": "B",
        "name": "Junction B",
        "phases": {
            "NS": ["NORTH", "SOUTH"],
            "EW": ["EAST", "WEST"],
        },
    }
    res_ok = await client.post("/api/junctions", json=valid_payload)
    assert res_ok.status_code == 201
    assert res_ok.json()["id"] == "B"

    # 3. Duplicate creation -> 409
    res_dup = await client.post("/api/junctions", json=valid_payload)
    assert res_dup.status_code == 409
    assert res_dup.json()["error"]["code"] == "JUNCTION_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_get_junction_by_id_and_not_found(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, _ = client_and_manager
    # Existing
    res = await client.get("/api/junctions/A")
    assert res.status_code == 200
    assert res.json()["id"] == "A"

    # Unknown
    res_404 = await client.get("/api/junctions/UNKNOWN")
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "JUNCTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_sensor_events_lifecycle(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, worker = client_and_manager

    # 1. Unknown junction -> 404
    res_404 = await client.post(
        "/api/sensor-events",
        json={
            "event_id": "evt-1",
            "junction_id": "UNKNOWN",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "V-1",
            "vehicle_type": "TRUCK",
            "sequence_no": 1,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert res_404.status_code == 404

    # 2. Unknown vehicle type (D-14) -> 422
    res_422 = await client.post(
        "/api/sensor-events",
        json={
            "event_id": "evt-2",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "V-2",
            "vehicle_type": "SUBMARINE",  # Invalid type!
            "sequence_no": 2,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert res_422.status_code == 422

    # 3. Valid arrival -> 201 APPLIED
    res_201 = await client.post(
        "/api/sensor-events",
        json={
            "event_id": "evt-3",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "V-100",
            "vehicle_type": "TRUCK",
            "sequence_no": 1,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert res_201.status_code == 201
    assert res_201.json()["status"] == "APPLIED"
    assert res_201.json()["duplicate"] is False

    # 4. Duplicate event -> 200 DUPLICATE (D-11, P-02)
    res_dup = await client.post(
        "/api/sensor-events",
        json={
            "event_id": "evt-3",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "V-100",
            "vehicle_type": "TRUCK",
            "sequence_no": 1,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert res_dup.status_code == 200
    assert res_dup.json()["status"] == "DUPLICATE"
    assert res_dup.json()["duplicate"] is True

    # 5. Clearance -> 201 APPLIED
    res_clear = await client.post(
        "/api/sensor-events",
        json={
            "event_id": "evt-4",
            "junction_id": "A",
            "direction": "NORTH",
            "event_type": "VEHICLE_CLEARED",
            "vehicle_id": "V-100",
            "sequence_no": 2,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert res_clear.status_code == 201
    assert res_clear.json()["status"] == "APPLIED"


@pytest.mark.asyncio
async def test_get_junction_status(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, _ = client_and_manager
    res = await client.get("/api/junctions/A/status")
    assert res.status_code == 200
    data = res.json()
    assert data["junction_id"] == "A"
    assert "desired_signals" in data
    assert "actual_signals" in data
    assert "queues" in data
    assert "transition" in data


@pytest.mark.asyncio
async def test_admin_commands_and_degraded_rejection(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, worker = client_and_manager

    # 1. Manual green request -> 202 ACCEPTED
    res = await client.post(
        "/api/junctions/A/commands",
        json={
            "command": "MANUAL_GREEN_REQUEST",
            "direction": "WEST",
            "issued_by": "admin-1",
        },
    )
    assert res.status_code == 202
    assert res.json()["status"] == "ACCEPTED"

    # 2. Return to automatic -> 202 ACCEPTED
    res_auto = await client.post(
        "/api/junctions/A/commands",
        json={
            "command": "RETURN_TO_AUTOMATIC",
            "issued_by": "admin-1",
        },
    )
    assert res_auto.status_code == 202

    # 3. Manual command when junction is DEGRADED -> 409 CONFLICT (P-04)
    from app.domain.types import Mode
    worker.state.mode = Mode.DEGRADED

    res_deg = await client.post(
        "/api/junctions/A/commands",
        json={
            "command": "MANUAL_GREEN_REQUEST",
            "direction": "NORTH",
            "issued_by": "admin-1",
        },
    )
    assert res_deg.status_code == 409
    assert res_deg.json()["error"]["code"] == "JUNCTION_DEGRADED"


@pytest.mark.asyncio
async def test_controller_events(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, worker = client_and_manager

    # Track a command
    from app.domain.effects import SendSignalCommand
    from app.domain.types import Direction, Signal
    cmd = SendSignalCommand(
        command_id="cmd-test-1", direction=Direction.NORTH, requested_state=Signal.GREEN
    )
    worker.command_tracker.record_command_sent(cmd, "A", 100.0)

    # 1. Valid ACK -> 200 PROCESSED
    res = await client.post(
        "/api/controller-events",
        json={
            "command_id": "cmd-test-1",
            "junction_id": "A",
            "direction": "NORTH",
            "status": "ACK",
            "actual_state": "GREEN",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "PROCESSED"

    # 2. Unknown command_id -> 404 (P-02)
    res_404 = await client.post(
        "/api/controller-events",
        json={
            "command_id": "cmd-nonexistent",
            "junction_id": "A",
            "direction": "NORTH",
            "status": "ACK",
            "actual_state": "GREEN",
        },
    )
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "COMMAND_NOT_FOUND"


@pytest.mark.asyncio
async def test_device_status_and_simulator_mode(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, worker = client_and_manager

    # 1. Device status reporting -> 200
    res_dev = await client.post(
        "/api/device-status",
        json={
            "event_id": "dev-01",
            "junction_id": "A",
            "device_type": "SIGNAL_CONTROLLER",
            "direction": "NORTH",
            "status": "ONLINE",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert res_dev.status_code == 200

    # 2. Set simulator mode -> 200
    res_sim = await client.post(
        "/api/simulator/A/mode",
        json={"mode": "SILENT"},
    )
    assert res_sim.status_code == 200
    assert res_sim.json()["mode"] == "SILENT"
    assert worker.simulator is not None
    assert worker.simulator.mode == "SILENT"

    # 3. Invalid mode -> 422
    res_bad = await client.post(
        "/api/simulator/A/mode",
        json={"mode": "FLYING"},
    )
    assert res_bad.status_code == 422


@pytest.mark.asyncio
async def test_history_endpoint(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    client, _ = client_and_manager
    res = await client.get("/api/junctions/A/history")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


@pytest.mark.asyncio
async def test_sse_stream_initial_event(
    client_and_manager: tuple[AsyncClient, JunctionWorker],
) -> None:
    _, worker = client_and_manager
    from unittest.mock import AsyncMock
    mock_request = AsyncMock()
    mock_request.is_disconnected.return_value = False

    from app.api.sse import sse_event_generator
    gen = sse_event_generator(worker, mock_request)
    first_event = await anext(gen)
    assert "event: status" in first_event
    assert '"junction_id": "A"' in first_event
    await gen.aclose()
