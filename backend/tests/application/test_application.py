"""Application runtime tests (Agent C).

Tests junction worker concurrency, controller failure/retries (D-19),
offline reconnect recovery, crash restart recovery (D-20),
and multi-junction isolation (D-01).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.application.junction_worker import JunctionWorker
from app.application.recovery import recover_junction
from app.domain.effects import SendSignalCommand
from app.domain.events import (
    AdminCommand,
    ControllerAck,
    ControllerNack,
    DeviceStatusChanged,
    VehicleArrived,
)
from app.domain.types import (
    Direction,
    JunctionConfig,
    Mode,
    Phase,
    Signal,
    Step,
    TimingsConfig,
    VehicleType,
)
from app.infrastructure.controllers.rest_simulator import (
    RestSimulatorController,
    SimulatorMode,
)
from app.infrastructure.db.models import Base
from app.infrastructure.db.repositories import (
    CommandRepository,
    JunctionRepository,
)


@pytest.fixture
async def app_fixture() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Setup SQLite in-memory engine and session factory."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as s:
        async with s.begin():
            repo = JunctionRepository(s)
            await repo.create("A", "Junction A", {})
            await repo.create("B", "Junction B", {})

    yield session_factory
    await engine.dispose()


def _make_config(junction_id: str = "A", ack_timeout: float = 0.5) -> JunctionConfig:
    return JunctionConfig(
        id=junction_id,
        name=f"Junction {junction_id}",
        phases={
            Phase.NS: [Direction.NORTH, Direction.SOUTH],
            Phase.EW: [Direction.EAST, Direction.WEST],
        },
        timings=TimingsConfig(
            green=2.0,
            yellow=0.5,
            all_red=0.2,
            min_green=0.5,
            max_green=5.0,
            ack_timeout=ack_timeout,
            max_retries=2,
            emergency_timeout=10.0,
            manual_lease=10.0,
        ),
    )


@pytest.mark.asyncio
async def test_concurrency_scenario_from_assessment(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Assessment Scenario 9: Concurrent events arriving close together.

    Sequence:
    T = 0 ms: NORTH truck arrives
    T = 4 ms: EAST emergency arrives
    T = 8 ms: Administrator requests WEST manual control
    T = 12 ms: Duplicate EAST emergency event arrives
    T = 17 ms: Controller ACK arrives
    Must remain consistent and never violate INV-1..INV-9.
    """
    config = _make_config("A")
    worker = JunctionWorker(
        junction_id="A",
        config=config,
        session_factory=app_fixture,
    )
    # Start in serving NS Green
    worker.state.serving = Phase.NS
    worker.state.step = Step.GREEN
    worker.state.mode = Mode.AUTOMATIC
    worker.state.desired[Direction.NORTH] = Signal.GREEN
    worker.state.desired[Direction.SOUTH] = Signal.GREEN
    worker.state.desired[Direction.EAST] = Signal.RED
    worker.state.desired[Direction.WEST] = Signal.RED
    worker.state.actual[Direction.NORTH] = Signal.GREEN
    worker.state.actual[Direction.SOUTH] = Signal.GREEN
    worker.state.actual[Direction.EAST] = Signal.RED
    worker.state.actual[Direction.WEST] = Signal.RED

    await worker.start()

    now = time.time()

    async def submit_t0() -> Any:
        await asyncio.sleep(0.000)
        return await worker.submit(
            VehicleArrived(
                event_id="evt-conc-0",
                junction_id="A",
                direction=Direction.NORTH,
                vehicle_id="VH-TRUCK-N",
                vehicle_type=VehicleType.TRUCK,
                sensor_time=now,
                server_time=now,
                sequence_no=100,
            )
        )

    async def submit_t4() -> Any:
        await asyncio.sleep(0.004)
        return await worker.submit(
            VehicleArrived(
                event_id="evt-conc-4",
                junction_id="A",
                direction=Direction.EAST,
                vehicle_id="VH-EMERG-E",
                vehicle_type=VehicleType.EMERGENCY,
                sensor_time=now + 0.004,
                server_time=now + 0.004,
                sequence_no=101,
            )
        )

    async def submit_t8() -> Any:
        await asyncio.sleep(0.008)
        return await worker.submit(
            AdminCommand(
                junction_id="A",
                command_type="MANUAL_GREEN_REQUEST",
                target_phase=Phase.EW,
                issued_by="admin-west",
                server_time=now + 0.008,
            )
        )

    async def submit_t12() -> Any:
        await asyncio.sleep(0.012)
        return await worker.submit(
            VehicleArrived(
                event_id="evt-conc-4",  # Duplicate event_id per scenario!
                junction_id="A",
                direction=Direction.EAST,
                vehicle_id="VH-EMERG-E",
                vehicle_type=VehicleType.EMERGENCY,
                sensor_time=now + 0.004,
                server_time=now + 0.012,
                sequence_no=101,
            )
        )

    async def submit_t17() -> Any:
        await asyncio.sleep(0.017)
        # Controller ACK
        return await worker.submit(
            ControllerAck(
                command_id="cmd-A-1-north-yellow",
                junction_id="A",
                direction=Direction.NORTH,
                confirmed_state=Signal.YELLOW,
                server_time=now + 0.017,
            )
        )

    results = await asyncio.gather(
        submit_t0(),
        submit_t4(),
        submit_t8(),
        submit_t12(),
        submit_t17(),
    )

    # 1. Duplicate event at T=12 returned duplicate: True
    res_t12 = results[3]
    assert res_t12.get("duplicate") is True

    # 2. Assert Invariant INV-1: NS and EW are never GREEN at the same time
    desired = worker.state.desired
    ns_green = desired[Direction.NORTH] == Signal.GREEN or desired[Direction.SOUTH] == Signal.GREEN
    ew_green = desired[Direction.EAST] == Signal.GREEN or desired[Direction.WEST] == Signal.GREEN
    assert not (ns_green and ew_green), "INV-1 violated: Conflicting GREENs!"

    # 3. Mode is EMERGENCY (Emergency overrides manual per D-15)
    assert worker.state.mode == Mode.EMERGENCY
    assert len(worker.state.emergencies) == 1
    assert worker.state.emergencies[0].vehicle_id == "VH-EMERG-E"

    await worker.stop()


@pytest.mark.asyncio
async def test_silent_controller_leads_to_degraded_after_retries(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Assessment Scenario 7: Controller does not acknowledge commands.

    SILENT -> retries -> DEGRADED -> ALL_RED requested (D-19).
    """
    config = _make_config("A", ack_timeout=0.1)  # 100ms timeout for fast testing
    sim = RestSimulatorController(junction_id="A", mode=SimulatorMode.SILENT)
    worker = JunctionWorker(
        junction_id="A",
        config=config,
        session_factory=app_fixture,
        controller=sim,
    )
    # Serving NS GREEN
    worker.state.serving = Phase.NS
    worker.state.step = Step.GREEN
    worker.state.mode = Mode.AUTOMATIC
    worker.state.desired = {
        Direction.NORTH: Signal.GREEN,
        Direction.SOUTH: Signal.GREEN,
        Direction.EAST: Signal.RED,
        Direction.WEST: Signal.RED,
    }
    await worker.start()

    # Trigger a transition: emergency vehicle arrives on EAST
    now = time.time()
    await worker.submit(
        VehicleArrived(
            event_id="evt-silent-1",
            junction_id="A",
            direction=Direction.EAST,
            vehicle_id="VH-EM-1",
            vehicle_type=VehicleType.EMERGENCY,
            sensor_time=now,
            server_time=now,
            sequence_no=1,
        )
    )

    # State machine should have commanded YELLOW for NORTH and SOUTH
    assert worker.state.step == Step.YELLOW
    assert len(worker.command_tracker.get_pending()) >= 1

    # Now let Ticker drive ticks past ACK timeout + 2 retries (3 ticks * 0.5s = 1.5s)
    await asyncio.sleep(1.6)

    # Mode must have degraded per D-19
    assert worker.state.mode == Mode.DEGRADED
    assert "SIGNAL_FAILURE" in worker.state.alerts
    # Actual signals must be UNKNOWN (INV-7, D-19)
    for d in Direction:
        assert worker.state.actual[d] == Signal.UNKNOWN
    # Desired signals must be RED (Fail-safe ALL_RED hold)
    for d in Direction:
        assert worker.state.desired[d] == Signal.RED

    await worker.stop()


@pytest.mark.asyncio
async def test_offline_then_reconnect_recovers_to_automatic(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """D-19: Controller OFFLINE enters DEGRADED.

    Reconnect requests ALL_RED and restores AUTOMATIC.
    """
    config = _make_config("A")
    worker = JunctionWorker(
        junction_id="A",
        config=config,
        session_factory=app_fixture,
    )
    await worker.start()

    # 1. Controller goes OFFLINE
    now = time.time()
    await worker.submit(
        DeviceStatusChanged(
            junction_id="A",
            device_type="SIGNAL_CONTROLLER",
            direction=None,
            status="OFFLINE",
            server_time=now,
        )
    )
    assert worker.state.mode == Mode.DEGRADED
    assert "CONTROLLER_OFFLINE" in worker.state.alerts
    for d in Direction:
        assert worker.state.actual[d] == Signal.UNKNOWN

    # 2. Controller reconnects (ONLINE)
    await worker.submit(
        DeviceStatusChanged(
            junction_id="A",
            device_type="SIGNAL_CONTROLLER",
            direction=None,
            status="ONLINE",
            server_time=now + 1.0,
        )
    )
    step_boot: Step = worker.state.step
    assert step_boot == Step.BOOT
    pending = worker.command_tracker.get_pending()
    for cmd in pending:
        await worker.submit(
            ControllerAck(
                command_id=cmd.command_id,
                junction_id="A",
                direction=cmd.direction,
                confirmed_state=Signal.RED,
                server_time=now + 1.1,
            )
        )

    # ALL_RED confirmed! Clears controller alert and enters ALL_RED step, recovering to AUTOMATIC
    step_final: Step = worker.state.step
    assert step_final == Step.ALL_RED
    assert "CONTROLLER_OFFLINE" not in worker.state.alerts
    mode_final: Mode = worker.state.mode
    assert mode_final == Mode.AUTOMATIC

    await worker.stop()


@pytest.mark.asyncio
async def test_kill_worker_mid_transition_and_recover(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Assessment Scenario 8 / D-20: Backend crash mid-transition and boot recovery.

    On boot: actual=UNKNOWN, pending commands ABANDONED, requests ALL_RED, awaits confirmation.
    """
    config = _make_config("A")
    worker1 = JunctionWorker(
        junction_id="A",
        config=config,
        session_factory=app_fixture,
    )
    await worker1.start()

    # Put worker1 mid-transition: step=YELLOW, pending commands
    worker1.state.step = Step.YELLOW
    worker1.state.actual[Direction.NORTH] = Signal.GREEN
    now = time.time()
    worker1.command_tracker.record_command_sent(
        SendSignalCommand("cmd-crash-1", Direction.NORTH, Signal.YELLOW), "A", now
    )

    # Simulate crash: stop worker1 abruptly
    await worker1.stop()

    # Create new worker simulating reboot
    worker2 = JunctionWorker(
        junction_id="A",
        config=config,
        session_factory=app_fixture,
    )
    await worker2.start()

    # Execute boot recovery
    await recover_junction("A", worker2, app_fixture)

    # D-20 / INV-8: No previously assumed physical state is assumed correct!
    for d in Direction:
        assert worker2.state.actual[d] == Signal.UNKNOWN
    assert worker2.state.step == Step.BOOT

    # Desired signals requested ALL_RED
    for d in Direction:
        assert worker2.state.desired[d] == Signal.RED

    await worker2.stop()


@pytest.mark.asyncio
async def test_multi_junction_200_events_never_block(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """D-01 / Multi-junction: 200 events across Junction A and B.

    Run concurrently without blocking.
    """
    config_a = _make_config("A")
    config_b = _make_config("B")

    worker_a = JunctionWorker("A", config_a, app_fixture)
    worker_b = JunctionWorker("B", config_b, app_fixture)

    await worker_a.start()
    await worker_b.start()

    now = time.time()
    tasks = []

    # 100 events to Junction A
    for i in range(100):
        tasks.append(
            worker_a.submit(
                VehicleArrived(
                    event_id=f"evt-A-{i}",
                    junction_id="A",
                    direction=Direction.NORTH if i % 2 == 0 else Direction.EAST,
                    vehicle_id=f"VA-{i}",
                    vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
                    sensor_time=now + i * 0.001,
                    server_time=now + i * 0.001,
                    sequence_no=i + 1,
                )
            )
        )

    # 100 events to Junction B
    for i in range(100):
        tasks.append(
            worker_b.submit(
                VehicleArrived(
                    event_id=f"evt-B-{i}",
                    junction_id="B",
                    direction=Direction.SOUTH if i % 2 == 0 else Direction.WEST,
                    vehicle_id=f"VB-{i}",
                    vehicle_type=VehicleType.FORKLIFT,
                    sensor_time=now + i * 0.001,
                    server_time=now + i * 0.001,
                    sequence_no=i + 1,
                )
            )
        )

    # Run all 200 events concurrently
    results = await asyncio.gather(*tasks)
    assert len(results) == 200
    for r in results:
        assert r.get("status") == "APPLIED"

    assert len(worker_a.state.waiting_vehicles) == 100
    assert len(worker_b.state.waiting_vehicles) == 100

    await worker_a.stop()
    await worker_b.stop()


@pytest.mark.asyncio
async def test_regression_boot_recovery_restores_waiting_vehicles_and_emergency_mode(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Regression test for D-20 / INV-8:
    Boot recovery must reload persistent waiting vehicles and re-derive emergencies.
    """
    config = _make_config("A")
    worker1 = JunctionWorker("A", config, app_fixture)
    await worker1.start()

    now = time.time()
    # 1. Ingest an EMERGENCY vehicle and a TRUCK
    res_arr1 = await worker1.submit(
        VehicleArrived(
            event_id="evt-boot-rec-1",
            junction_id="A",
            direction=Direction.EAST,
            vehicle_id="VH-EMERG-BOOT",
            vehicle_type=VehicleType.EMERGENCY,
            sensor_time=now,
            server_time=now,
            sequence_no=1,
        )
    )
    assert res_arr1["status"] == "APPLIED"

    res_arr2 = await worker1.submit(
        VehicleArrived(
            event_id="evt-boot-rec-2",
            junction_id="A",
            direction=Direction.NORTH,
            vehicle_id="VH-TRUCK-BOOT",
            vehicle_type=VehicleType.TRUCK,
            sensor_time=now,
            server_time=now,
            sequence_no=1,
        )
    )
    assert res_arr2["status"] == "APPLIED"

    assert len(worker1.state.waiting_vehicles) == 2
    await worker1.stop()

    # 2. Simulate crash and reboot with fresh JunctionWorker
    worker2 = JunctionWorker("A", config, app_fixture)
    await worker2.start()

    # Worker starts with empty state before recovery
    assert len(worker2.state.waiting_vehicles) == 0

    # Execute boot recovery per D-20
    await recover_junction("A", worker2, app_fixture)

    # 3. Invariants & requirements verification
    # INV-8: Actual signals UNKNOWN
    for d in Direction:
        assert worker2.state.actual[d] == Signal.UNKNOWN
    # Desired signals requested ALL_RED
    for d in Direction:
        assert worker2.state.desired[d] == Signal.RED
    assert worker2.state.step == Step.BOOT

    # D-20: Waiting vehicles restored into memory
    assert len(worker2.state.waiting_vehicles) == 2
    veh_ids = {v.vehicle_id for v in worker2.state.waiting_vehicles}
    assert "VH-EMERG-BOOT" in veh_ids
    assert "VH-TRUCK-BOOT" in veh_ids

    # D-20: Emergency mode re-derived from persistent WAITING emergency vehicle
    assert worker2.state.mode == Mode.EMERGENCY
    assert len(worker2.state.emergencies) == 1
    assert worker2.state.emergencies[0].vehicle_id == "VH-EMERG-BOOT"

    # Status queues properly report non-zero counts
    status_dict = worker2.get_status_dict()
    assert status_dict["queues"]["EAST"] == 1
    assert status_dict["queues"]["NORTH"] == 1
    assert status_dict["emergency"]["active"] is True
    assert status_dict["emergency"]["vehicle_id"] == "VH-EMERG-BOOT"

    await worker2.stop()


@pytest.mark.asyncio
async def test_regression_boot_recovery_restores_active_manual_lease(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Regression test for D-20: Active manual lease is preserved across restarts."""
    config = _make_config("A")
    worker1 = JunctionWorker("A", config, app_fixture)
    await worker1.start()

    now = time.time()
    await worker1.submit(
        AdminCommand(
            junction_id="A",
            command_type="MANUAL_GREEN_REQUEST",
            target_phase=Phase.EW,
            issued_by="operator-recovery",
            server_time=now,
        )
    )
    assert worker1.state.mode == Mode.MANUAL
    assert worker1.state.manual.active is True
    await worker1.stop()

    # Reboot worker and recover
    worker2 = JunctionWorker("A", config, app_fixture)
    await worker2.start()
    await recover_junction("A", worker2, app_fixture)

    # Manual mode and unexpired lease maintained per D-20
    assert worker2.state.mode == Mode.MANUAL
    assert worker2.state.manual.active is True
    assert worker2.state.manual.issued_by == "operator-recovery"
    assert worker2.state.manual.target_phase == Phase.EW

    await worker2.stop()


@pytest.mark.asyncio
async def test_regression_controller_nack_marks_command_failed_in_db_and_rejects_unknown(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Regression test for D-19 / openapi:
    Controller NACK marks command FAILED in DB and rejects unknown commands.
    """
    config = _make_config("A")
    sim = RestSimulatorController(junction_id="A", mode=SimulatorMode.SILENT)
    worker = JunctionWorker("A", config, app_fixture, controller=sim)
    worker.state.serving = Phase.NS
    worker.state.step = Step.GREEN
    worker.state.mode = Mode.AUTOMATIC
    worker.state.desired = {
        Direction.NORTH: Signal.GREEN,
        Direction.SOUTH: Signal.GREEN,
        Direction.EAST: Signal.RED,
        Direction.WEST: Signal.RED,
    }
    await worker.start()

    now = time.time()
    # 1. Trigger transition so that commands are dispatched
    await worker.submit(
        VehicleArrived(
            event_id="evt-nack-test",
            junction_id="A",
            direction=Direction.EAST,
            vehicle_id="VH-NACK-1",
            vehicle_type=VehicleType.EMERGENCY,
            sensor_time=now,
            server_time=now,
            sequence_no=1,
        )
    )

    pending_cmds = worker.command_tracker.get_pending()
    assert len(pending_cmds) >= 1
    target_cmd = pending_cmds[0]

    async with app_fixture() as session:
        repo = CommandRepository(session)
        db_cmd = await repo.get(target_cmd.command_id)
        assert db_cmd is not None
        assert db_cmd.status == "PENDING"

    # 2. Submit ControllerNack for target_cmd
    nack_res = await worker.submit(
        ControllerNack(
            command_id=target_cmd.command_id,
            junction_id="A",
            direction=target_cmd.direction,
            reason="Hardware relay fault",
            server_time=now + 0.1,
        )
    )
    assert nack_res.get("status") == "PROCESSED"

    # Command status in DB updated to FAILED (D-19)
    async with app_fixture() as session:
        repo = CommandRepository(session)
        updated_db_cmd = await repo.get(target_cmd.command_id)
        assert updated_db_cmd is not None
        assert updated_db_cmd.status == "FAILED"

    # 3. Submit ControllerNack for unknown command_id
    unknown_res = await worker.submit(
        ControllerNack(
            command_id="cmd-completely-unknown",
            junction_id="A",
            direction=Direction.NORTH,
            reason="Invalid",
            server_time=now + 0.2,
        )
    )
    assert unknown_res.get("not_found") is True

    await worker.stop()


@pytest.mark.asyncio
async def test_regression_sensor_offline_reports_stale_queues_and_device_status(
    app_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """Regression test for D-19 / openapi:
    Sensor offline marks direction in stale_queues and device_statuses.
    """
    config = _make_config("A")
    worker = JunctionWorker("A", config, app_fixture)
    await worker.start()

    now = time.time()
    # Sensor for WEST goes OFFLINE
    await worker.submit(
        DeviceStatusChanged(
            junction_id="A",
            device_type="SENSOR",
            direction=Direction.WEST,
            status="OFFLINE",
            server_time=now,
        )
    )

    st = worker.get_status_dict()
    assert "WEST" in st["stale_queues"]
    assert st["device_statuses"]["SENSOR_WEST"]["status"] == "OFFLINE"

    # Sensor for WEST recovers to ONLINE
    await worker.submit(
        DeviceStatusChanged(
            junction_id="A",
            device_type="SENSOR",
            direction=Direction.WEST,
            status="ONLINE",
            server_time=now + 1.0,
        )
    )

    st_recovered = worker.get_status_dict()
    assert "WEST" not in st_recovered["stale_queues"]
    assert st_recovered["device_statuses"]["SENSOR_WEST"]["status"] == "ONLINE"

    await worker.stop()

