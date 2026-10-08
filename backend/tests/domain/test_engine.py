"""Domain engine tests.

Tests for domain engine state transitions, decisions D-07..D-20, and invariants INV-1..INV-9.
"""

from __future__ import annotations

import pytest

from app.domain.config import validate_junction_config
from app.domain.effects import Alert, RecordAudit, SendSignalCommand
from app.domain.engine import process_event
from app.domain.events import (
    AdminCommand,
    Boot,
    ControllerAck,
    ControllerNack,
    DeviceStatusChanged,
    Tick,
    VehicleArrived,
    VehicleCleared,
)
from app.domain.scoring import calculate_phase_scores, select_next_phase
from app.domain.types import (
    ALERT_CONTROLLER_OFFLINE,
    ALERT_SIGNAL_FAILURE,
    Direction,
    JunctionConfig,
    JunctionState,
    ManualState,
    Mode,
    Phase,
    Signal,
    Step,
    TimingsConfig,
    VehicleType,
    WaitingVehicle,
)


def _make_active_green_ns_state() -> JunctionState:
    """Helper creating a standard Junction A state serving Phase.NS at Step.GREEN."""
    return JunctionState(
        version=1,
        mode=Mode.AUTOMATIC,
        serving=Phase.NS,
        step=Step.GREEN,
        desired={
            Direction.NORTH: Signal.GREEN,
            Direction.SOUTH: Signal.GREEN,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
        actual={
            Direction.NORTH: Signal.GREEN,
            Direction.SOUTH: Signal.GREEN,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
    )


def test_emergency_preemption_initiates_yellow_transition() -> None:
    """INV-3, INV-4, D-15: Emergency on EAST while NS is GREEN initiates transition to YELLOW."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    emergency_event = VehicleArrived(
        event_id="evt-em-1",
        junction_id="A",
        direction=Direction.EAST,
        vehicle_id="EM-999",
        vehicle_type=VehicleType.EMERGENCY,
        sensor_time=100.0,
        server_time=100.0,
        sequence_no=1,
    )

    new_state, effects = process_event(state, config, emergency_event, now=100.0)

    # Preemption should transition desired NS to YELLOW and emit YELLOW commands
    assert new_state.step == Step.YELLOW
    assert new_state.desired[Direction.NORTH] == Signal.YELLOW
    assert new_state.desired[Direction.SOUTH] == Signal.YELLOW
    assert any(
        isinstance(e, SendSignalCommand)
        and e.direction == Direction.NORTH
        and e.requested_state == Signal.YELLOW
        for e in effects
    )
    assert any(
        isinstance(e, SendSignalCommand)
        and e.direction == Direction.SOUTH
        and e.requested_state == Signal.YELLOW
        for e in effects
    )


def test_regression_emergency_preemption_original_bug() -> None:
    """Regression test: Phase 0 stub returned Step.GREEN instead of Step.YELLOW on emergency."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    emergency_event = VehicleArrived(
        event_id="evt-em-reg-1",
        junction_id="A",
        direction=Direction.WEST,
        vehicle_id="EM-REG-1",
        vehicle_type=VehicleType.EMERGENCY,
        sensor_time=200.0,
        server_time=200.0,
        sequence_no=1,
    )

    new_state, effects = process_event(state, config, emergency_event, now=200.0)

    # Must NOT stay GREEN
    assert new_state.step != Step.GREEN
    assert new_state.step == Step.YELLOW
    assert new_state.mode == Mode.EMERGENCY
    assert new_state.target == Phase.EW
    assert len(new_state.emergencies) == 1
    assert new_state.emergencies[0].vehicle_id == "EM-REG-1"


def test_emergency_preemption_full_sequence_to_green() -> None:
    """INV-2, INV-3, INV-4, D-08, D-15: Full transition sequence YELLOW -> ALL_RED -> GREEN."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    # Step 1: Emergency arrives on EAST
    em_event = VehicleArrived(
        event_id="evt-em-2",
        junction_id="A",
        direction=Direction.EAST,
        vehicle_id="EM-1",
        vehicle_type=VehicleType.EMERGENCY,
        sensor_time=100.0,
        server_time=100.0,
        sequence_no=1,
    )
    s1, fx1 = process_event(state, config, em_event, now=100.0)
    assert s1.step == Step.YELLOW
    assert s1.deadline_at is None  # waiting for YELLOW ACKs

    # Controller ACKs YELLOW for NORTH and SOUTH
    ack_n_yellow = ControllerAck(
        command_id=s1.pending_command_ids[0],
        junction_id="A",
        direction=Direction.NORTH,
        confirmed_state=Signal.YELLOW,
        server_time=101.0,
    )
    s2, _ = process_event(s1, config, ack_n_yellow, now=101.0)
    assert s2.deadline_at is None  # still waiting for SOUTH

    ack_s_yellow = ControllerAck(
        command_id=s2.pending_command_ids[0],
        junction_id="A",
        direction=Direction.SOUTH,
        confirmed_state=Signal.YELLOW,
        server_time=102.0,
    )
    s3, _ = process_event(s2, config, ack_s_yellow, now=102.0)
    assert s3.deadline_at == 102.0 + config.timings.yellow  # Yellow hold timer started

    # Tick before yellow deadline: remains in yellow
    s4, _ = process_event(s3, config, Tick(junction_id="A", server_time=105.0), now=105.0)
    assert s4.step == Step.YELLOW

    # Tick at yellow deadline: emits RED commands for NS
    s5, fx5 = process_event(s4, config, Tick(junction_id="A", server_time=107.0), now=107.0)
    assert s5.desired[Direction.NORTH] == Signal.RED
    assert s5.desired[Direction.SOUTH] == Signal.RED
    assert any(
        isinstance(e, SendSignalCommand)
        and e.direction == Direction.NORTH
        and e.requested_state == Signal.RED
        for e in fx5
    )

    # Controller ACKs RED for NORTH and SOUTH
    ack_n_red = ControllerAck(
        command_id=s5.pending_command_ids[0],
        junction_id="A",
        direction=Direction.NORTH,
        confirmed_state=Signal.RED,
        server_time=107.5,
    )
    s6, _ = process_event(s5, config, ack_n_red, now=107.5)

    ack_s_red = ControllerAck(
        command_id=s6.pending_command_ids[0],
        junction_id="A",
        direction=Direction.SOUTH,
        confirmed_state=Signal.RED,
        server_time=108.0,
    )
    s7, _ = process_event(s6, config, ack_s_red, now=108.0)
    assert s7.step == Step.ALL_RED
    assert s7.deadline_at == 108.0 + config.timings.all_red

    # Tick at all_red deadline: since NS confirmed RED, emits GREEN for EW
    s8, fx8 = process_event(s7, config, Tick(junction_id="A", server_time=110.0), now=110.0)
    assert s8.desired[Direction.EAST] == Signal.GREEN
    assert s8.desired[Direction.WEST] == Signal.GREEN
    assert any(
        isinstance(e, SendSignalCommand)
        and e.direction == Direction.EAST
        and e.requested_state == Signal.GREEN
        for e in fx8
    )

    # Controller ACKs GREEN for EAST and WEST
    ack_e_green = ControllerAck(
        command_id=s8.pending_command_ids[0],
        junction_id="A",
        direction=Direction.EAST,
        confirmed_state=Signal.GREEN,
        server_time=110.5,
    )
    s9, _ = process_event(s8, config, ack_e_green, now=110.5)

    ack_w_green = ControllerAck(
        command_id=s9.pending_command_ids[0],
        junction_id="A",
        direction=Direction.WEST,
        confirmed_state=Signal.GREEN,
        server_time=111.0,
    )
    s10, _ = process_event(s9, config, ack_w_green, now=111.0)
    assert s10.step == Step.GREEN
    assert s10.serving == Phase.EW
    assert s10.target is None
    assert s10.deadline_at == 111.0 + config.timings.green


def test_d07_timings_configurable() -> None:
    """D-07: Junction timings are configurable and respected by the engine."""
    custom_timings = TimingsConfig(green=15.0, yellow=3.0, all_red=1.0)
    config = JunctionConfig(id="A", name="Custom", timings=custom_timings)
    state = _make_active_green_ns_state()

    # Trigger emergency
    em = VehicleArrived("e1", "A", Direction.EAST, "EM-1", VehicleType.EMERGENCY, 50.0, 50.0, 1)
    s1, _ = process_event(state, config, em, now=50.0)

    # ACK yellows
    for cmd_id in list(s1.pending_command_ids):
        direction = Direction.NORTH if "north" in cmd_id else Direction.SOUTH
        s1, _ = process_event(
            s1,
            config,
            ControllerAck(cmd_id, "A", direction, Signal.YELLOW, 51.0),
            now=51.0,
        )

    # Yellow deadline should use custom yellow (3.0s) -> 51.0 + 3.0 = 54.0
    assert s1.deadline_at == 54.0


def test_d08_inv2_green_not_emitted_until_opposing_red_confirmed() -> None:
    """D-08, INV-2: GREEN for Phase EW must not be emitted until NS is confirmed RED."""
    config = JunctionConfig(id="A", name="Junction A")
    state = JunctionState(
        version=5,
        mode=Mode.AUTOMATIC,
        serving=Phase.NS,
        step=Step.ALL_RED,
        target=Phase.EW,
        deadline_at=100.0,
        desired={
            Direction.NORTH: Signal.RED,
            Direction.SOUTH: Signal.RED,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
        # actual NORTH is still YELLOW, unconfirmed RED!
        actual={
            Direction.NORTH: Signal.YELLOW,
            Direction.SOUTH: Signal.RED,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
    )

    # Tick at deadline 100.0: should NOT emit GREEN because actual NORTH is not RED!
    new_state, effects = process_event(
        state, config, Tick(junction_id="A", server_time=100.0), now=100.0
    )
    assert not any(
        isinstance(e, SendSignalCommand) and e.requested_state == Signal.GREEN for e in effects
    )
    assert new_state.step == Step.ALL_RED
    assert new_state.desired[Direction.EAST] == Signal.RED


def test_d09_scoring_weights_and_25_percent_threshold() -> None:
    """D-09: Scoring respects vehicle weights and 25% switch threshold."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    # 1 truck on NS (weight 3)
    state.waiting_vehicles.append(
        WaitingVehicle("v1", Direction.NORTH, VehicleType.TRUCK, 100.0, 1)
    )
    # 1 forklift on EW (weight 2)
    state.waiting_vehicles.append(
        WaitingVehicle("v2", Direction.EAST, VehicleType.FORKLIFT, 100.0, 2)
    )

    scores = calculate_phase_scores(state, config, now=100.0)
    assert scores[Phase.NS] == 3.0
    assert scores[Phase.EW] == 2.0

    # Challenger (EW) has 2.0, Serving (NS) has 3.0. Challenger does not beat serving by 25%.
    assert select_next_phase(state, config, now=100.0) == Phase.NS

    # Add another truck to EW -> EW has weight 5.0 > 3.0 * 1.25 (3.75)
    state.waiting_vehicles.append(WaitingVehicle("v3", Direction.WEST, VehicleType.TRUCK, 100.0, 3))
    scores2 = calculate_phase_scores(state, config, now=100.0)
    assert scores2[Phase.EW] == 5.0
    assert select_next_phase(state, config, now=100.0) == Phase.EW


def test_d09_starvation_protection_lone_employee_served() -> None:
    """D-09: Lone employee vehicle waiting >= 90s forces next phase even against heavier traffic."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    # Heavy traffic on currently serving NS (5 trucks arrived recently)
    for i in range(5):
        state.waiting_vehicles.append(
            WaitingVehicle(
                f"trk-{i}", Direction.NORTH, VehicleType.TRUCK, arrived_at=95.0, sequence_no=i
            )
        )

    # Lone employee vehicle waiting for 91 seconds on EAST (arrived at 9.0, now is 100.0)
    state.waiting_vehicles.append(
        WaitingVehicle(
            "emp-1", Direction.EAST, VehicleType.EMPLOYEE_VEHICLE, arrived_at=9.0, sequence_no=10
        )
    )

    # Starvation protection must force EW to be selected next
    selected = select_next_phase(state, config, now=100.0)
    assert selected == Phase.EW


def test_d09_no_cycling_with_empty_queues() -> None:
    """D-09: Empty queues anywhere results in staying on the current phase (no cycling)."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()
    state.waiting_vehicles = []

    assert select_next_phase(state, config, now=100.0) == Phase.NS


def test_d10_config_validation() -> None:
    """D-10: Config validation rejects invalid phase definitions and negative timings."""
    # Valid config passes
    valid_cfg = JunctionConfig(id="A", name="Valid")
    validate_junction_config(valid_cfg)

    # Empty ID fails
    with pytest.raises(ValueError, match="Junction ID"):
        validate_junction_config(JunctionConfig(id="", name="Valid"))

    # Overlapping directions fail
    bad_phases = JunctionConfig(
        id="A",
        name="Bad",
        phases={
            Phase.NS: [Direction.NORTH, Direction.SOUTH, Direction.EAST],
            Phase.EW: [Direction.EAST, Direction.WEST],
        },
    )
    with pytest.raises(ValueError, match="disjoint"):
        validate_junction_config(bad_phases)

    # Negative timing fails
    bad_timings = JunctionConfig(id="A", name="Bad", timings=TimingsConfig(green=-10.0))
    with pytest.raises(ValueError, match="positive"):
        validate_junction_config(bad_timings)


def test_d11_inv6_duplicate_arrival_does_not_duplicate_queue() -> None:
    """D-11, INV-6: Processing duplicate vehicle arrival does not increase queue."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    evt1 = VehicleArrived("e-1", "A", Direction.NORTH, "VH-1", VehicleType.TRUCK, 10.0, 10.0, 1)
    s1, fx1 = process_event(state, config, evt1, now=10.0)
    assert len(s1.waiting_vehicles) == 1

    # Same arrival again
    s2, fx2 = process_event(s1, config, evt1, now=11.0)
    assert len(s2.waiting_vehicles) == 1  # Queue unchanged
    assert any(isinstance(e, RecordAudit) and e.event_type == "DUPLICATE_SENSOR_EVENT" for e in fx2)


def test_d12_stale_sensor_event_ignored() -> None:
    """D-12: Event with sensor_time differing by > 5m is flagged stale and ignored."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    # Sensor time is 100.0, server time is 500.0 (diff 400s > 300s limit)
    stale_evt = VehicleArrived(
        "e-stale", "A", Direction.EAST, "EM-STALE", VehicleType.EMERGENCY, 100.0, 500.0, 1
    )
    s1, fx = process_event(state, config, stale_evt, now=500.0)

    # Queues and emergencies unchanged
    assert len(s1.waiting_vehicles) == 0
    assert len(s1.emergencies) == 0
    assert s1.mode == Mode.AUTOMATIC
    assert any(isinstance(e, RecordAudit) and e.event_type == "STALE_SENSOR_EVENT" for e in fx)


def test_d13_orphan_clear_queue_never_negative() -> None:
    """D-13, INV-6: Orphan clear records audit and queue count stays 0."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()
    assert len(state.waiting_vehicles) == 0

    orphan_evt = VehicleCleared("c-1", "A", Direction.NORTH, "UNKNOWN-VH", 10.0, 10.0, 1)
    s1, fx = process_event(state, config, orphan_evt, now=10.0)

    assert len(s1.waiting_vehicles) == 0  # Queue remains 0, never negative
    assert any(isinstance(e, RecordAudit) and e.event_type == "ORPHAN_CLEARED" for e in fx)


def test_d15_emergency_overrides_manual() -> None:
    """D-15: Emergency preemption overrides manual override and returns to AUTO on clear."""
    config = JunctionConfig(id="A", name="Junction A")

    state = _make_active_green_ns_state()

    # Admin takes manual control for NS
    cmd = AdminCommand("A", "MANUAL_GREEN_REQUEST", Phase.NS, "admin1", 50.0)
    s1, _ = process_event(state, config, cmd, now=50.0)
    assert s1.mode == Mode.MANUAL
    assert s1.manual.active is True

    # Emergency on EAST arrives
    em = VehicleArrived("e-em", "A", Direction.EAST, "EM-10", VehicleType.EMERGENCY, 60.0, 60.0, 1)
    s2, fx2 = process_event(s1, config, em, now=60.0)

    # Emergency takes over and initiates transition
    assert s2.mode == Mode.EMERGENCY
    assert s2.step == Step.YELLOW
    assert s2.target == Phase.EW

    # Emergency clears -> junction returns to AUTOMATIC (D-15)
    clr = VehicleCleared("c-em", "A", Direction.EAST, "EM-10", 70.0, 70.0, 2)
    s3, fx3 = process_event(s2, config, clr, now=70.0)
    assert s3.mode == Mode.AUTOMATIC
    assert any(
        isinstance(e, RecordAudit)
        and e.event_type == "MODE_CHANGED"
        and e.payload.get("mode") == Mode.AUTOMATIC.value
        for e in fx3
    )


def test_d16_competing_emergencies_fcfs() -> None:
    """D-16: First-come first-served for conflicting emergencies (no flip-flopping)."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    # Emergency on NORTH (Phase NS) arrives while serving NS -> handled immediately
    em_north = VehicleArrived(
        "e-n", "A", Direction.NORTH, "EM-N", VehicleType.EMERGENCY, 10.0, 10.0, 1
    )
    s1, _ = process_event(state, config, em_north, now=10.0)
    assert s1.mode == Mode.EMERGENCY
    assert s1.step == Step.GREEN  # already serving NS

    # Conflicting emergency on EAST (Phase EW) arrives
    em_east = VehicleArrived(
        "e-e", "A", Direction.EAST, "EM-E", VehicleType.EMERGENCY, 12.0, 12.0, 2
    )
    s2, _ = process_event(s1, config, em_east, now=12.0)

    # D-16: Active emergency on NS is NOT preempted mid-stream by EW
    assert s2.step == Step.GREEN
    assert s2.serving == Phase.NS
    assert s2.target == Phase.EW  # EW queued as next target


def test_d16_same_phase_emergencies_served_together() -> None:
    """D-16: Emergencies on the same phase (NORTH and SOUTH) are served together."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    em_n = VehicleArrived("e-n", "A", Direction.NORTH, "EM-N", VehicleType.EMERGENCY, 10.0, 10.0, 1)
    s1, _ = process_event(state, config, em_n, now=10.0)

    em_s = VehicleArrived("e-s", "A", Direction.SOUTH, "EM-S", VehicleType.EMERGENCY, 11.0, 11.0, 2)
    s2, _ = process_event(s1, config, em_s, now=11.0)

    assert len(s2.emergencies) == 2
    assert s2.step == Step.GREEN
    assert s2.serving == Phase.NS


def test_d17_emergency_timeout_clears_mode() -> None:
    """D-17: Stale emergency times out after 120s on Tick and returns mode to AUTOMATIC."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    em = VehicleArrived("e-1", "A", Direction.EAST, "EM-1", VehicleType.EMERGENCY, 10.0, 10.0, 1)
    s1, _ = process_event(state, config, em, now=10.0)
    assert s1.mode == Mode.EMERGENCY

    # Tick before timeout (10.0 + 120.0 = 130.0)
    s2, _ = process_event(s1, config, Tick(junction_id="A", server_time=120.0), now=120.0)
    assert len(s2.emergencies) == 1
    assert s2.mode == Mode.EMERGENCY

    # Tick past timeout (131.0)
    s3, fx3 = process_event(s2, config, Tick(junction_id="A", server_time=131.0), now=131.0)
    assert len(s3.emergencies) == 0
    assert s3.mode == Mode.AUTOMATIC
    assert any(isinstance(e, RecordAudit) and e.event_type == "EMERGENCY_TIMEOUT" for e in fx3)


def test_d18_manual_lease_expires() -> None:
    """D-18: Manual control is a 5-minute lease (300s); expires on Tick and returns to AUTOMATIC."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    cmd = AdminCommand("A", "MANUAL_GREEN_REQUEST", Phase.NS, "admin", 100.0)
    s1, _ = process_event(state, config, cmd, now=100.0)
    assert s1.mode == Mode.MANUAL
    assert s1.manual.active is True
    assert s1.manual.lease_expires_at == 400.0

    # Tick at 399.0: lease active
    s2, _ = process_event(s1, config, Tick(junction_id="A", server_time=399.0), now=399.0)
    assert s2.mode == Mode.MANUAL

    # Tick at 401.0: lease expired
    s3, fx = process_event(s2, config, Tick(junction_id="A", server_time=401.0), now=401.0)
    assert s3.mode == Mode.AUTOMATIC
    assert s3.manual.active is False
    assert any(isinstance(e, RecordAudit) and e.event_type == "MANUAL_LEASE_EXPIRED" for e in fx)


def test_d19_controller_nack_triggers_degraded_and_all_red() -> None:
    """D-19, INV-9: Controller NACK sets junction to DEGRADED and requests fail-safe ALL_RED."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    nack = ControllerNack("cmd-xyz", "A", Direction.NORTH, "Hardware fault", 100.0)
    new_state, effects = process_event(state, config, nack, now=100.0)

    assert new_state.mode == Mode.DEGRADED
    assert ALERT_SIGNAL_FAILURE in new_state.alerts
    assert any(isinstance(e, Alert) and e.alert_type == ALERT_SIGNAL_FAILURE for e in effects)
    # Fail safe: all directions requested RED
    for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
        assert new_state.desired[d] == Signal.RED


def test_d19_controller_offline_alert_and_unknown_actual() -> None:
    """D-19: Controller OFFLINE triggers DEGRADED mode and sets actual to UNKNOWN."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    offline_evt = DeviceStatusChanged("A", "SIGNAL_CONTROLLER", None, "OFFLINE", 100.0)
    new_state, effects = process_event(state, config, offline_evt, now=100.0)

    assert new_state.mode == Mode.DEGRADED
    assert ALERT_CONTROLLER_OFFLINE in new_state.alerts
    for d in Direction:
        assert new_state.actual[d] == Signal.UNKNOWN


def test_d19_late_or_duplicate_ack_ignored() -> None:
    """D-19: Unsolicited or late ACK is audited and does not mutate transition progress."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()
    state.pending_command_ids = []

    untracked_ack = ControllerAck("cmd-old-99", "A", Direction.NORTH, Signal.GREEN, 100.0)
    new_state, effects = process_event(state, config, untracked_ack, now=100.0)

    assert any(
        isinstance(e, RecordAudit) and e.event_type == "CONTROLLER_ACK_UNTRACKED" for e in effects
    )


def test_d20_inv8_restart_recovery_actual_unknown_all_red() -> None:
    """D-20, INV-8: Boot sets actual to UNKNOWN, requests ALL_RED, and re-derives emergencies."""
    config = JunctionConfig(id="A", name="Junction A")
    state = JunctionState(
        version=10,
        mode=Mode.AUTOMATIC,
        serving=Phase.NS,
        step=Step.GREEN,
        desired={d: Signal.GREEN for d in Direction},
        actual={d: Signal.GREEN for d in Direction},
        waiting_vehicles=[
            WaitingVehicle("em-boot", Direction.EAST, VehicleType.EMERGENCY, 10.0, 1),
            WaitingVehicle("vh-normal", Direction.NORTH, VehicleType.TRUCK, 10.0, 2),
        ],
    )

    boot_evt = Boot(junction_id="A", server_time=50.0)
    new_state, effects = process_event(state, config, boot_evt, now=50.0)

    # Invariant INV-8: actual states are UNKNOWN
    for d in Direction:
        assert new_state.actual[d] == Signal.UNKNOWN
        assert new_state.desired[d] == Signal.RED

    assert new_state.step == Step.BOOT
    # Re-derived emergency
    assert len(new_state.emergencies) == 1
    assert new_state.emergencies[0].vehicle_id == "em-boot"
    assert new_state.mode == Mode.EMERGENCY
    # Emitted ALL_RED commands
    assert (
        len(
            [
                e
                for e in effects
                if isinstance(e, SendSignalCommand) and e.requested_state == Signal.RED
            ]
        )
        == 4
    )


def test_inv9_degraded_mode_emits_no_green() -> None:
    """INV-9: In DEGRADED mode, no GREEN command is ever emitted on any event."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()
    state.mode = Mode.DEGRADED

    # Try manual green request
    cmd = AdminCommand("A", "MANUAL_GREEN_REQUEST", Phase.EW, "admin", 100.0)
    s1, fx1 = process_event(state, config, cmd, now=100.0)
    assert not any(
        isinstance(e, SendSignalCommand) and e.requested_state == Signal.GREEN for e in fx1
    )

    # Try emergency
    em = VehicleArrived("em", "A", Direction.EAST, "EM-1", VehicleType.EMERGENCY, 101.0, 101.0, 1)
    s2, fx2 = process_event(s1, config, em, now=101.0)
    assert not any(
        isinstance(e, SendSignalCommand) and e.requested_state == Signal.GREEN for e in fx2
    )

    # Try tick
    s3, fx3 = process_event(s2, config, Tick(junction_id="A", server_time=102.0), now=102.0)
    assert not any(
        isinstance(e, SendSignalCommand) and e.requested_state == Signal.GREEN for e in fx3
    )


def test_regression_emergency_during_all_red_with_green_commanded_no_deadlock() -> None:
    """Bug 1 Regression: Emergency arrival while green commands in flight must not deadlock."""
    config = JunctionConfig(id="A", name="Junction A")
    state = JunctionState(
        version=1,
        mode=Mode.AUTOMATIC,
        serving=Phase.NS,
        step=Step.ALL_RED,
        target=Phase.EW,
        deadline_at=10.0,
        desired={
            Direction.NORTH: Signal.RED,
            Direction.SOUTH: Signal.RED,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
        actual={
            Direction.NORTH: Signal.RED,
            Direction.SOUTH: Signal.RED,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
    )

    # Step 5: Tick triggers GREEN commands for EW
    s1, fx1 = process_event(state, config, Tick("A", 10.0), now=10.0)
    assert s1.desired[Direction.EAST] == Signal.GREEN
    assert s1.desired[Direction.WEST] == Signal.GREEN
    assert s1.target == Phase.EW

    # Conflicting emergency arrives on NORTH (Phase.NS) while waiting for EW GREEN ACKs
    em = VehicleArrived("e-1", "A", Direction.NORTH, "EM-N", VehicleType.EMERGENCY, 10.1, 10.1, 1)
    s2, fx2 = process_event(s1, config, em, now=10.1)

    # In flight target must NOT be corrupted
    assert s2.target == Phase.EW
    assert s2.desired[Direction.EAST] == Signal.GREEN

    # Controller ACKs GREEN for EAST and WEST
    ack_e = ControllerAck(s1.pending_command_ids[0], "A", Direction.EAST, Signal.GREEN, 10.2)
    s3, _ = process_event(s2, config, ack_e, now=10.2)
    ack_w = ControllerAck(s1.pending_command_ids[1], "A", Direction.WEST, Signal.GREEN, 10.3)
    s4, fx4 = process_event(s3, config, ack_w, now=10.3)

    # Now that EW confirmed GREEN, queued emergency on NS immediately initiates preemption
    assert s4.serving == Phase.EW
    assert s4.step == Step.YELLOW
    assert s4.target == Phase.NS
    assert s4.desired[Direction.EAST] == Signal.YELLOW
    assert s4.desired[Direction.WEST] == Signal.YELLOW


def test_regression_d16_fcfs_competing_emergencies_arrival_order() -> None:
    """Bug 2 Regression: D-16 First-come first-served for conflicting emergencies."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    # Emergency 1 on EAST at T=10.0s (Phase.EW)
    em1 = VehicleArrived("e-1", "A", Direction.EAST, "EM-E", VehicleType.EMERGENCY, 10.0, 10.0, 1)
    s1, _ = process_event(state, config, em1, now=10.0)
    assert s1.step == Step.YELLOW
    assert s1.target == Phase.EW

    # Emergency 2 on NORTH arrives at T=11.0s (Phase.NS)
    em2 = VehicleArrived("e-2", "A", Direction.NORTH, "EM-N", VehicleType.EMERGENCY, 11.0, 11.0, 2)
    s2, _ = process_event(s1, config, em2, now=11.0)

    # First emergency phase EW must NOT be preempted/overwritten by later emergency
    assert s2.target == Phase.EW
    assert len(s2.emergencies) == 2
    assert s2.emergencies[0].vehicle_id == "EM-E"


def test_regression_d15_emergency_terminates_manual_no_revival() -> None:
    """Bug 3 Regression: D-15 Emergency clears manual state, and clear returns cleanly to AUTO."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    # Admin takes manual control
    cmd = AdminCommand("A", "MANUAL_GREEN_REQUEST", Phase.NS, "admin1", 50.0)
    s1, _ = process_event(state, config, cmd, now=50.0)
    assert s1.mode == Mode.MANUAL
    assert s1.manual.active is True

    # Emergency on EAST arrives
    em = VehicleArrived("e-em", "A", Direction.EAST, "EM-10", VehicleType.EMERGENCY, 60.0, 60.0, 1)
    s2, _ = process_event(s1, config, em, now=60.0)
    assert s2.mode == Mode.EMERGENCY
    assert s2.manual.active is False  # Manual terminated

    # Admin command during emergency is rejected
    cmd2 = AdminCommand("A", "MANUAL_GREEN_REQUEST", Phase.NS, "admin2", 65.0)
    s2_cmd, fx_cmd = process_event(s2, config, cmd2, now=65.0)
    assert any(isinstance(e, RecordAudit) and e.event_type == "COMMAND_REJECTED" for e in fx_cmd)

    # Emergency clears
    clr = VehicleCleared("c-em", "A", Direction.EAST, "EM-10", 70.0, 70.0, 2)
    s3, _ = process_event(s2_cmd, config, clr, now=70.0)
    assert s3.mode == Mode.AUTOMATIC
    assert s3.manual.active is False  # Does NOT revive manual


def test_regression_d19_controller_nack_sets_actual_unknown() -> None:
    """Bug 4 Regression: D-19 ControllerNack must mark actual signals UNKNOWN."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    nack = ControllerNack("cmd-xyz", "A", Direction.NORTH, "Hardware fault", 100.0)
    s1, _ = process_event(state, config, nack, now=100.0)

    assert s1.mode == Mode.DEGRADED
    for d in Direction:
        assert s1.actual[d] == Signal.UNKNOWN
        assert s1.desired[d] == Signal.RED


def test_regression_d19_controller_reconnect_recovers_to_automatic() -> None:
    """Bug 5 Regression: D-19 Controller reconnect recovers from DEGRADED via ALL_RED."""
    config = JunctionConfig(id="A", name="Junction A")
    state = JunctionState(
        version=1,
        mode=Mode.DEGRADED,
        serving=Phase.NS,
        step=Step.ALL_RED,
        desired={d: Signal.RED for d in Direction},
        actual={d: Signal.UNKNOWN for d in Direction},
        alerts=[ALERT_CONTROLLER_OFFLINE],
    )

    # Controller reconnects
    online_evt = DeviceStatusChanged("A", "SIGNAL_CONTROLLER", None, "ONLINE", 100.0)
    s1, fx1 = process_event(state, config, online_evt, now=100.0)
    assert s1.step == Step.BOOT
    assert len(s1.pending_command_ids) == 4

    # Controller confirms ALL_RED
    for cmd_id in list(s1.pending_command_ids):
        d = Direction.NORTH if "north" in cmd_id else (
            Direction.SOUTH if "south" in cmd_id else (
                Direction.EAST if "east" in cmd_id else Direction.WEST
            )
        )
        ack = ControllerAck(cmd_id, "A", d, Signal.RED, 101.0)
        s1, _ = process_event(s1, config, ack, now=101.0)

    # Successfully recovered to AUTOMATIC
    assert s1.mode == Mode.AUTOMATIC
    assert s1.step == Step.ALL_RED
    assert ALERT_CONTROLLER_OFFLINE not in s1.alerts
    assert s1.deadline_at == 101.0 + config.timings.all_red


def test_regression_d20_restart_mid_transition_clears_target() -> None:
    """Bug 6 Regression: D-20 Boot recovery mid-transition clears target for fresh queue."""
    config = JunctionConfig(id="A", name="Junction A")
    state = JunctionState(
        version=1,
        mode=Mode.AUTOMATIC,
        serving=Phase.NS,
        step=Step.YELLOW,
        target=Phase.EW,  # Mid-transition to EW when server crashed
        desired={
            Direction.NORTH: Signal.YELLOW,
            Direction.SOUTH: Signal.YELLOW,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
        actual={
            Direction.NORTH: Signal.YELLOW,
            Direction.SOUTH: Signal.YELLOW,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
        waiting_vehicles=[
            WaitingVehicle("em-restart", Direction.NORTH, VehicleType.EMERGENCY, 10.0, 1)
        ],
    )

    boot = Boot("A", 50.0)
    s1, _ = process_event(state, config, boot, now=50.0)

    # Target must be reset to None on Boot
    assert s1.target is None
    assert s1.mode == Mode.EMERGENCY  # Re-derived from waiting emergency on NS


def test_regression_p04_return_to_automatic_accepted_in_degraded() -> None:
    """Bug 7 Regression: P-04 RETURN_TO_AUTOMATIC is accepted in DEGRADED mode."""
    config = JunctionConfig(id="A", name="Junction A")
    state = JunctionState(
        version=1,
        mode=Mode.DEGRADED,
        manual=ManualState(active=True, target_phase=Phase.NS, issued_by="admin"),
    )

    cmd = AdminCommand("A", "RETURN_TO_AUTOMATIC", None, "admin", 50.0)
    s1, fx = process_event(state, config, cmd, now=50.0)

    assert s1.manual.active is False
    assert any(
        isinstance(e, RecordAudit) and e.event_type == "RETURN_TO_AUTOMATIC_ACCEPTED" for e in fx
    )


def test_d14_unknown_vehicle_types_rejected() -> None:
    """D-14: Unknown vehicle types are rejected."""
    valid_types = {v.value for v in VehicleType}
    assert valid_types == {"EMERGENCY", "TRUCK", "FORKLIFT", "EMPLOYEE_VEHICLE"}
    with pytest.raises(ValueError):
        VehicleType("MATERIAL_CARRIER")


def test_repeated_emergency_event_does_not_duplicate_or_retrigger() -> None:
    """Instruction specific case: Repeated emergency event changes queue once."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    em = VehicleArrived("e-1", "A", Direction.EAST, "EM-1", VehicleType.EMERGENCY, 10.0, 10.0, 1)
    s1, _ = process_event(state, config, em, now=10.0)
    assert len(s1.waiting_vehicles) == 1
    assert len(s1.emergencies) == 1

    # Same emergency arrival again
    s2, fx2 = process_event(s1, config, em, now=10.5)
    assert len(s2.waiting_vehicles) == 1
    assert len(s2.emergencies) == 1
    assert any(isinstance(e, RecordAudit) and e.event_type == "DUPLICATE_SENSOR_EVENT" for e in fx2)


def test_ack_never_arrives_holds_transition_safely() -> None:
    """Instruction specific case: INV-2, INV-7, D-08 If ACK never arrives, state machine holds."""
    config = JunctionConfig(id="A", name="Junction A")
    state = _make_active_green_ns_state()

    em = VehicleArrived("e-1", "A", Direction.EAST, "EM-1", VehicleType.EMERGENCY, 10.0, 10.0, 1)
    s1, _ = process_event(state, config, em, now=10.0)
    assert s1.step == Step.YELLOW
    assert s1.deadline_at is None

    # Ticks pass, but controller never ACKs
    for t in [11.0, 15.0, 30.0, 60.0]:
        s1, fx = process_event(s1, config, Tick("A", t), now=t)
        assert s1.step == Step.YELLOW
        # Never emits RED or GREEN without ACK
        assert not any(
            isinstance(e, SendSignalCommand) and e.requested_state in (Signal.RED, Signal.GREEN)
            for e in fx
        )

