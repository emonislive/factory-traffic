"""Scenario integration test suite for Factory Traffic Management System.

Covers all 9 assessment scenarios from Assessment Section 15 and Instruction.md Section 8:
1. Normal Traffic: Score-based switching, minimum green hold, no needless switching.
2. Priority Traffic: TRUCK priority over EMPLOYEE_VEHICLE with equal queue size.
3. Emergency Preemption: Immediate preemption sequence YELLOW -> ALL_RED -> GREEN, INV-1..4.
4. Manual Override: Lease, Return to Automatic, Emergency preemption terminates manual.
5. Duplicate Event: 200 DUPLICATE response, queue counts unchanged.
6. Vehicle Clearance: Waiting queue decrements, orphan clearance handled cleanly.
7. Controller Failure: SILENT mode -> retries -> DEGRADED mode -> fail-safe ALL_RED.
8. Restart Recovery: Reboot mid-transition resets actual=UNKNOWN, requests ALL_RED.
9. Concurrent Events: T=0..17ms rapid sequence processed in strict serialized order.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.junction_worker import JunctionWorker, get_junction_manager
from app.application.recovery import recover_junction
from app.domain.scoring import calculate_phase_scores
from app.domain.types import (
    Direction,
    JunctionConfig,
    Mode,
    Phase,
    Signal,
    Step,
    TimingsConfig,
)
from app.infrastructure.controllers.rest_simulator import (
    RestSimulatorController,
    SimulatorMode,
)
from app.infrastructure.db.models import Base
from app.infrastructure.db.repositories import (
    AuditLogRepository,
    JunctionRepository,
)
from app.infrastructure.db.session import set_engine
from app.main import create_app


@pytest.fixture
async def scenario_client() -> AsyncGenerator[AsyncClient, None]:
    """Setup test database and FastAPI client for scenario testing."""
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

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Cleanup workers
    for worker in list(manager._workers.values()):
        await worker.stop()
    await engine.dispose()


async def _create_test_junction(
    client: AsyncClient,
    junction_id: str,
    ack_timeout: float = 0.5,
    min_green: float = 0.2,
    green: float = 1.0,
    simulator_mode: SimulatorMode = SimulatorMode.AUTO_ACK,
) -> JunctionWorker:
    """Helper to create and initialize a registered junction with worker."""
    manager = get_junction_manager()
    config = JunctionConfig(
        id=junction_id,
        name=f"Junction {junction_id}",
        phases={
            Phase.NS: [Direction.NORTH, Direction.SOUTH],
            Phase.EW: [Direction.EAST, Direction.WEST],
        },
        timings=TimingsConfig(
            green=green,
            yellow=0.3,
            all_red=0.1,
            min_green=min_green,
            max_green=5.0,
            ack_timeout=ack_timeout,
            max_retries=2,
            emergency_timeout=10.0,
            manual_lease=10.0,
        ),
    )
    controller = RestSimulatorController(junction_id=junction_id, mode=simulator_mode)
    worker = JunctionWorker(
        junction_id=junction_id,
        config=config,
        session_factory=manager.session_factory,
        controller=controller,
    )
    manager._workers[junction_id] = worker
    await worker.start()

    # Save junction metadata to DB
    async with manager.session_factory() as s:
        async with s.begin():
            repo = JunctionRepository(s)
            await repo.create(
                junction_id,
                f"Junction {junction_id}",
                {
                    "phases": {"NS": ["NORTH", "SOUTH"], "EW": ["EAST", "WEST"]},
                    "timings": {
                        "green": green,
                        "yellow": 0.3,
                        "all_red": 0.1,
                        "min_green": min_green,
                        "max_green": 5.0,
                        "ack_timeout": ack_timeout,
                        "max_retries": 2,
                    },
                },
            )

    return worker


# ---------------------------------------------------------------------------
# Scenario 1: Normal Traffic (Score-based switching, no needless switching)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_1_normal_traffic(scenario_client: AsyncClient) -> None:
    """Scenario 1: Highest-score phase gets served; no needless switching."""
    worker = await _create_test_junction(
        scenario_client, "S1", min_green=0.1, green=0.5
    )

    # Initial state: serving NS GREEN
    worker.state.serving = Phase.NS
    worker.state.step = Step.GREEN
    worker.state.mode = Mode.AUTOMATIC
    worker.state.deadline_at = time.time()
    worker.state.desired[Direction.NORTH] = Signal.GREEN
    worker.state.desired[Direction.SOUTH] = Signal.GREEN
    worker.state.actual[Direction.NORTH] = Signal.GREEN
    worker.state.actual[Direction.SOUTH] = Signal.GREEN

    # Arrival of 2 TRUCK vehicles on EAST
    now = datetime.now(UTC).isoformat()
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s1-arr-1",
            "junction_id": "S1",
            "direction": "EAST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-S1-E1",
            "vehicle_type": "TRUCK",
            "sequence_no": 1,
            "timestamp": now,
        },
    )
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s1-arr-2",
            "junction_id": "S1",
            "direction": "EAST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-S1-E2",
            "vehicle_type": "TRUCK",
            "sequence_no": 2,
            "timestamp": now,
        },
    )

    res = await scenario_client.get("/api/junctions/S1/status")
    assert res.status_code == 200
    data = res.json()
    assert data["queues"]["EAST"] == 2

    # Wait for min_green to elapse and ticker to switch phases to EW
    await asyncio.sleep(2.0)

    res2 = await scenario_client.get("/api/junctions/S1/status")
    data2 = res2.json()
    # High score on EW triggered transition
    assert data2["phase"] == "EW"
    assert data2["actual_signals"]["EAST"] == "GREEN"


# ---------------------------------------------------------------------------
# Scenario 2: Priority Traffic (TRUCK beats EMPLOYEE_VEHICLE)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_2_priority_traffic(scenario_client: AsyncClient) -> None:
    """Scenario 2: TRUCK (weight 3) beats EMPLOYEE_VEHICLE (weight 1) with equal queue size."""
    worker = await _create_test_junction(scenario_client, "S2", min_green=0.1)

    now = datetime.now(UTC).isoformat()
    # 1 TRUCK on NORTH
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s2-arr-n",
            "junction_id": "S2",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-TRUCK-1",
            "vehicle_type": "TRUCK",
            "sequence_no": 1,
            "timestamp": now,
        },
    )
    # 1 EMPLOYEE_VEHICLE on EAST
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s2-arr-e",
            "junction_id": "S2",
            "direction": "EAST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-EMP-1",
            "vehicle_type": "EMPLOYEE_VEHICLE",
            "sequence_no": 1,
            "timestamp": now,
        },
    )

    res = await scenario_client.get("/api/junctions/S2/status")
    data = res.json()
    assert data["queues"]["NORTH"] == 1
    assert data["queues"]["EAST"] == 1

    # Check scoring: NORTH (TRUCK) has score 3, EAST (EMP) has score 1
    scores = calculate_phase_scores(worker.state, worker.config, time.time())
    assert scores[Phase.NS] > scores[Phase.EW]


# ---------------------------------------------------------------------------
# Scenario 3: Emergency Preemption (YELLOW -> ALL_RED -> GREEN, INV-1..4)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_3_emergency_preemption(scenario_client: AsyncClient) -> None:
    """Scenario 3: Emergency preemption immediately begins transition sequence."""
    worker = await _create_test_junction(scenario_client, "S3")

    # Serving NS GREEN
    worker.state.serving = Phase.NS
    worker.state.step = Step.GREEN
    worker.state.mode = Mode.AUTOMATIC
    worker.state.desired[Direction.NORTH] = Signal.GREEN
    worker.state.actual[Direction.NORTH] = Signal.GREEN

    # Emergency vehicle arrives on conflicting direction WEST
    now = datetime.now(UTC).isoformat()
    res = await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s3-emerg-1",
            "junction_id": "S3",
            "direction": "WEST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-AMB-1",
            "vehicle_type": "EMERGENCY",
            "sequence_no": 1,
            "timestamp": now,
        },
    )
    assert res.status_code == 201

    # Check status: Emergency mode active, target is EW, step is YELLOW
    status_res = await scenario_client.get("/api/junctions/S3/status")
    status_data = status_res.json()
    assert status_data["mode"] == "EMERGENCY"
    assert status_data["emergency"]["active"] is True
    assert status_data["emergency"]["direction"] == "WEST"
    assert status_data["emergency"]["vehicle_id"] == "VH-AMB-1"
    assert status_data["transition"]["step"] == "YELLOW"
    assert status_data["transition"]["target"] == "EW"

    # Allow controller simulator AUTO_ACK to advance transition
    await asyncio.sleep(2.0)

    final_status = await scenario_client.get("/api/junctions/S3/status")
    final_data = final_status.json()
    assert final_data["phase"] == "EW"
    assert final_data["actual_signals"]["WEST"] == "GREEN"


# ---------------------------------------------------------------------------
# Scenario 4: Manual Override (Lease, Return to Auto, Emergency Preempts Manual)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_4_manual_override(scenario_client: AsyncClient) -> None:
    """Scenario 4: Manual control lease, Return to Automatic, and Emergency preemption."""
    _ = await _create_test_junction(scenario_client, "S4")

    # 1. Request manual green
    cmd_res = await scenario_client.post(
        "/api/junctions/S4/commands",
        json={
            "command": "MANUAL_GREEN_REQUEST",
            "direction": "EAST",
            "issued_by": "operator-bob",
        },
    )
    assert cmd_res.status_code == 202

    status1 = await scenario_client.get("/api/junctions/S4/status")
    d1 = status1.json()
    assert d1["mode"] == "MANUAL"
    assert d1["manual"]["active"] is True
    assert d1["manual"]["issued_by"] == "operator-bob"

    # 2. Emergency arrival overrides manual control (D-15)
    now = datetime.now(UTC).isoformat()
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s4-emerg",
            "junction_id": "S4",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-EMERG-4",
            "vehicle_type": "EMERGENCY",
            "sequence_no": 1,
            "timestamp": now,
        },
    )

    status2 = await scenario_client.get("/api/junctions/S4/status")
    d2 = status2.json()
    assert d2["mode"] == "EMERGENCY"
    assert d2["manual"]["active"] is False  # D-15: manual deactivated!

    # 3. Return to automatic
    ret_res = await scenario_client.post(
        "/api/junctions/S4/commands",
        json={
            "command": "RETURN_TO_AUTOMATIC",
            "issued_by": "operator-bob",
        },
    )
    assert ret_res.status_code == 202


# ---------------------------------------------------------------------------
# Scenario 5: Duplicate Event (Idempotent 200 DUPLICATE, queue unchanged)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_5_duplicate_event(scenario_client: AsyncClient) -> None:
    """Scenario 5: Duplicate sensor event returns 200 DUPLICATE and leaves queue unchanged."""
    await _create_test_junction(scenario_client, "S5")

    now = datetime.now(UTC).isoformat()
    payload = {
        "event_id": "s5-dup-event-1",
        "junction_id": "S5",
        "direction": "SOUTH",
        "event_type": "VEHICLE_ARRIVED",
        "vehicle_id": "VH-DUP-5",
        "vehicle_type": "FORKLIFT",
        "sequence_no": 10,
        "timestamp": now,
    }

    # First ingestion -> 201 APPLIED
    res1 = await scenario_client.post("/api/sensor-events", json=payload)
    assert res1.status_code == 201
    assert res1.json()["status"] == "APPLIED"
    assert res1.json()["duplicate"] is False

    # Second ingestion of exact same event_id -> 200 DUPLICATE (D-11, P-02)
    res2 = await scenario_client.post("/api/sensor-events", json=payload)
    assert res2.status_code == 200
    assert res2.json()["status"] == "DUPLICATE"
    assert res2.json()["duplicate"] is True

    # Check status: South queue is exactly 1, not 2
    status_res = await scenario_client.get("/api/junctions/S5/status")
    assert status_res.json()["queues"]["SOUTH"] == 1


# ---------------------------------------------------------------------------
# Scenario 6: Vehicle Clearance & Orphan Handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_6_vehicle_clearance(scenario_client: AsyncClient) -> None:
    """Scenario 6: Vehicle clearance decrements queue; orphan clear is safely handled."""
    await _create_test_junction(scenario_client, "S6")

    now = datetime.now(UTC).isoformat()
    # Arrival
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s6-arr",
            "junction_id": "S6",
            "direction": "NORTH",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-CLEAR-1",
            "vehicle_type": "TRUCK",
            "sequence_no": 1,
            "timestamp": now,
        },
    )

    q1 = (await scenario_client.get("/api/junctions/S6/status")).json()["queues"]["NORTH"]
    assert q1 == 1

    # Clearance -> 201 APPLIED
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s6-clr",
            "junction_id": "S6",
            "direction": "NORTH",
            "event_type": "VEHICLE_CLEARED",
            "vehicle_id": "VH-CLEAR-1",
            "sequence_no": 2,
            "timestamp": now,
        },
    )

    q2 = (await scenario_client.get("/api/junctions/S6/status")).json()["queues"]["NORTH"]
    assert q2 == 0

    # Orphan clearance for non-waiting vehicle -> 202 NOT_APPLIED
    res_orphan = await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s6-orphan",
            "junction_id": "S6",
            "direction": "EAST",
            "event_type": "VEHICLE_CLEARED",
            "vehicle_id": "VH-NONEXISTENT",
            "sequence_no": 10,
            "timestamp": now,
        },
    )
    assert res_orphan.status_code == 202
    assert res_orphan.json()["status"] == "NOT_APPLIED"

    # Queue counts remain 0, never negative (INV-5)
    q3 = (await scenario_client.get("/api/junctions/S6/status")).json()["queues"]["EAST"]
    assert q3 == 0


# ---------------------------------------------------------------------------
# Scenario 7: Controller Failure (SILENT -> retries -> DEGRADED -> ALL_RED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_7_controller_failure(scenario_client: AsyncClient) -> None:
    """Scenario 7: Unresponsive controller enters DEGRADED and requests fail-safe ALL_RED."""
    worker = await _create_test_junction(
        scenario_client, "S7", ack_timeout=0.1, simulator_mode=SimulatorMode.SILENT
    )

    worker.state.serving = Phase.NS
    worker.state.step = Step.GREEN
    worker.state.mode = Mode.AUTOMATIC
    worker.state.desired[Direction.NORTH] = Signal.GREEN
    worker.state.actual[Direction.NORTH] = Signal.GREEN

    # Trigger transition to EW via emergency vehicle
    now = datetime.now(UTC).isoformat()
    await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s7-emerg",
            "junction_id": "S7",
            "direction": "EAST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-S7-E",
            "vehicle_type": "EMERGENCY",
            "sequence_no": 1,
            "timestamp": now,
        },
    )

    # Let ticker process timeout + 2 retries (0.1s ack_timeout)
    await asyncio.sleep(1.6)

    status_res = await scenario_client.get("/api/junctions/S7/status")
    data = status_res.json()
    assert data["mode"] == "DEGRADED"
    assert "SIGNAL_FAILURE" in data["alerts"]
    for d in ["NORTH", "SOUTH", "EAST", "WEST"]:
        assert data["desired_signals"][d] == "RED"
        assert data["actual_signals"][d] == "UNKNOWN"


# ---------------------------------------------------------------------------
# Scenario 8: Restart Recovery (D-20: actual=UNKNOWN, ALL_RED confirmed)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_8_restart_recovery(scenario_client: AsyncClient) -> None:
    """Scenario 8: System reboot mid-transition resets actual=UNKNOWN and enforces ALL_RED."""
    worker = await _create_test_junction(scenario_client, "S8")

    # Ingest a waiting vehicle before crash to test persistence recovery
    now_iso = datetime.now(UTC).isoformat()
    arr_res = await scenario_client.post(
        "/api/sensor-events",
        json={
            "event_id": "s8-arr-truck",
            "junction_id": "S8",
            "direction": "EAST",
            "event_type": "VEHICLE_ARRIVED",
            "vehicle_id": "VH-S8-TRUCK",
            "vehicle_type": "TRUCK",
            "sequence_no": 1,
            "timestamp": now_iso,
        },
    )
    assert arr_res.status_code == 201

    # Put worker mid-transition and save audit log
    worker.state.step = Step.YELLOW
    worker.state.actual[Direction.NORTH] = Signal.GREEN

    manager = get_junction_manager()
    async with manager.session_factory() as s:
        async with s.begin():
            audit_repo = AuditLogRepository(s)
            await audit_repo.append(
                junction_id="S8",
                event_type="STATE_CHANGE",
                direction="NORTH",
                previous_state="GREEN",
                new_state="YELLOW",
                reason="Preemption transition",
                source="SYSTEM",
            )

    # Stop worker to simulate crash
    await worker.stop()

    # Reboot worker and run boot recovery
    rebooted = JunctionWorker("S8", worker.config, manager.session_factory)
    manager._workers["S8"] = rebooted
    await rebooted.start()
    await recover_junction("S8", rebooted, manager.session_factory)

    # D-20 / INV-8: No physical state assumed, actual=UNKNOWN, requested ALL_RED
    status_res = await scenario_client.get("/api/junctions/S8/status")
    data = status_res.json()
    for d in ["NORTH", "SOUTH", "EAST", "WEST"]:
        assert data["actual_signals"][d] == "UNKNOWN"
        assert data["desired_signals"][d] == "RED"
    assert data["transition"]["step"] == "BOOT"

    # D-20: Persistent waiting vehicles preserved across restart
    assert data["queues"]["EAST"] == 1
    assert len(rebooted.state.waiting_vehicles) == 1
    assert rebooted.state.waiting_vehicles[0].vehicle_id == "VH-S8-TRUCK"

    # History in audit log preserved
    hist_res = await scenario_client.get("/api/junctions/S8/history")
    assert hist_res.status_code == 200
    assert len(hist_res.json()) >= 1


# ---------------------------------------------------------------------------
# Scenario 9: Concurrent Events (T=0..17ms sequence integrity)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_9_concurrent_events(scenario_client: AsyncClient) -> None:
    """Scenario 9: Rapid concurrent events (T=0..17ms) preserve serialized consistency."""
    worker = await _create_test_junction(scenario_client, "S9")

    worker.state.serving = Phase.NS
    worker.state.step = Step.GREEN
    worker.state.desired[Direction.NORTH] = Signal.GREEN
    worker.state.actual[Direction.NORTH] = Signal.GREEN

    iso_now = datetime.now(UTC).isoformat()

    async def send_t0() -> None:
        await asyncio.sleep(0.000)
        await scenario_client.post(
            "/api/sensor-events",
            json={
                "event_id": "evt-s9-0",
                "junction_id": "S9",
                "direction": "NORTH",
                "event_type": "VEHICLE_ARRIVED",
                "vehicle_id": "VH-9-TRUCK",
                "vehicle_type": "TRUCK",
                "sequence_no": 1,
                "timestamp": iso_now,
            },
        )

    async def send_t4() -> None:
        await asyncio.sleep(0.004)
        await scenario_client.post(
            "/api/sensor-events",
            json={
                "event_id": "evt-s9-4",
                "junction_id": "S9",
                "direction": "EAST",
                "event_type": "VEHICLE_ARRIVED",
                "vehicle_id": "VH-9-EMERG",
                "vehicle_type": "EMERGENCY",
                "sequence_no": 1,
                "timestamp": iso_now,
            },
        )

    async def send_t8() -> None:
        await asyncio.sleep(0.008)
        await scenario_client.post(
            "/api/junctions/S9/commands",
            json={
                "command": "MANUAL_GREEN_REQUEST",
                "direction": "WEST",
                "issued_by": "admin-s9",
            },
        )

    async def send_t12() -> None:
        await asyncio.sleep(0.012)
        # Duplicate of t4
        await scenario_client.post(
            "/api/sensor-events",
            json={
                "event_id": "evt-s9-4",
                "junction_id": "S9",
                "direction": "EAST",
                "event_type": "VEHICLE_ARRIVED",
                "vehicle_id": "VH-9-EMERG",
                "vehicle_type": "EMERGENCY",
                "sequence_no": 1,
                "timestamp": iso_now,
            },
        )

    # Execute all concurrently
    await asyncio.gather(send_t0(), send_t4(), send_t8(), send_t12())

    # Wait for queue to process
    await asyncio.sleep(0.1)

    status_res = await scenario_client.get("/api/junctions/S9/status")
    data = status_res.json()

    # Emergency overrides manual (D-15), mode is EMERGENCY
    assert data["mode"] == "EMERGENCY"
    assert data["emergency"]["active"] is True
    assert data["emergency"]["vehicle_id"] == "VH-9-EMERG"
    # Duplicate was not double-counted
    assert data["queues"]["EAST"] == 1
    assert data["queues"]["NORTH"] == 1
