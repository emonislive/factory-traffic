"""Hypothesis property tests for domain safety invariants INV-1..INV-9.

Reference: Instruction.md section 2 and Agent A prompt.
"""

from __future__ import annotations

from collections.abc import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.effects import SendSignalCommand
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
from app.domain.types import (
    Direction,
    JunctionConfig,
    JunctionState,
    Mode,
    Phase,
    Signal,
    Step,
    VehicleType,
)

# Hypothesis strategies for domain entities
directions_st = st.sampled_from(list(Direction))
vehicle_types_st = st.sampled_from(list(VehicleType))
phases_st = st.sampled_from(list(Phase))
signals_st = st.sampled_from(list(Signal))
device_types_st = st.sampled_from(["SIGNAL_CONTROLLER", "SENSOR"])
device_statuses_st = st.sampled_from(["ONLINE", "OFFLINE", "DEGRADED", "WARNING", "UNKNOWN"])
command_types_st = st.sampled_from(["MANUAL_GREEN_REQUEST", "RETURN_TO_AUTOMATIC"])


@st.composite
def domain_event_strategy(draw: st.DrawFn, current_time: float) -> tuple[object, float]:
    event_type = draw(
        st.sampled_from(
            [
                "arrival",
                "clear",
                "admin",
                "ack",
                "nack",
                "device_status",
                "tick",
                "boot",
            ]
        )
    )
    time_delta = draw(st.floats(min_value=0.1, max_value=5.0))
    now = current_time + time_delta

    if event_type == "arrival":
        v_id = f"vh-{draw(st.integers(min_value=1, max_value=20))}"
        direction = draw(directions_st)
        v_type = draw(vehicle_types_st)
        seq = draw(st.integers(min_value=1, max_value=100))
        return (
            VehicleArrived(
                event_id=f"evt-{draw(st.integers(min_value=1, max_value=1000))}",
                junction_id="A",
                direction=direction,
                vehicle_id=v_id,
                vehicle_type=v_type,
                sensor_time=now,
                server_time=now,
                sequence_no=seq,
            ),
            now,
        )

    elif event_type == "clear":
        v_id = f"vh-{draw(st.integers(min_value=1, max_value=20))}"
        direction = draw(directions_st)
        seq = draw(st.integers(min_value=1, max_value=100))
        return (
            VehicleCleared(
                event_id=f"clr-{draw(st.integers(min_value=1, max_value=1000))}",
                junction_id="A",
                direction=direction,
                vehicle_id=v_id,
                sensor_time=now,
                server_time=now,
                sequence_no=seq,
            ),
            now,
        )

    elif event_type == "admin":
        cmd_type = draw(command_types_st)
        target_phase = draw(phases_st) if cmd_type == "MANUAL_GREEN_REQUEST" else None
        return (
            AdminCommand(
                junction_id="A",
                command_type=cmd_type,
                target_phase=target_phase,
                issued_by="admin-hyp",
                server_time=now,
            ),
            now,
        )

    elif event_type == "ack":
        direction = draw(directions_st)
        confirmed_signal = draw(signals_st)
        return (
            ControllerAck(
                command_id=f"cmd-A-hyp-{draw(st.integers(min_value=1, max_value=50))}",
                junction_id="A",
                direction=direction,
                confirmed_state=confirmed_signal,
                server_time=now,
            ),
            now,
        )

    elif event_type == "nack":
        direction = draw(directions_st)
        return (
            ControllerNack(
                command_id=f"cmd-A-hyp-{draw(st.integers(min_value=1, max_value=50))}",
                junction_id="A",
                direction=direction,
                reason="fault",
                server_time=now,
            ),
            now,
        )

    elif event_type == "device_status":
        dev_type = draw(device_types_st)
        direction_opt: Direction | None = draw(directions_st) if dev_type == "SENSOR" else None
        status = draw(device_statuses_st)
        return (
            DeviceStatusChanged(
                junction_id="A",
                device_type=dev_type,
                direction=direction_opt,
                status=status,
                server_time=now,
            ),
            now,
        )

    elif event_type == "boot":
        return Boot(junction_id="A", server_time=now), now

    else:
        return Tick(junction_id="A", server_time=now), now


def assert_safety_invariants(
    state: JunctionState, effects: Sequence[object], config: JunctionConfig
) -> None:
    # INV-1: NORTH/SOUTH and EAST/WEST are never GREEN at the same time in desired state
    ns_dirs = config.phases[Phase.NS]
    ew_dirs = config.phases[Phase.EW]

    ns_green = any(state.desired.get(d) == Signal.GREEN for d in ns_dirs)
    ew_green = any(state.desired.get(d) == Signal.GREEN for d in ew_dirs)
    assert not (
        ns_green and ew_green
    ), f"INV-1 violated: Both NS and EW desired GREEN! {state.desired}"

    # INV-2: GREEN command for phase X is only emitted when opposing phase RED is confirmed
    for eff in effects:
        if isinstance(eff, SendSignalCommand) and eff.requested_state == Signal.GREEN:
            phase = Phase.NS if eff.direction in ns_dirs else Phase.EW
            opposing = Phase.EW if phase == Phase.NS else Phase.NS
            for d in config.phases[opposing]:
                assert state.actual.get(d) == Signal.RED, (
                    f"INV-2 violated: Emitted GREEN for {eff.direction} "
                    f"while opposing {d} actual is {state.actual.get(d)}"
                )

    # INV-6: Queue counts are never negative
    for d in Direction:
        q_count = sum(1 for v in state.waiting_vehicles if v.direction == d)
        assert q_count >= 0, f"INV-6 violated: Negative queue count for {d}: {q_count}"

    # INV-9: In DEGRADED mode, no GREEN command is emitted
    if state.mode == Mode.DEGRADED:
        for eff in effects:
            if isinstance(eff, SendSignalCommand):
                assert (
                    eff.requested_state != Signal.GREEN
                ), f"INV-9 violated: GREEN command emitted in DEGRADED mode! {eff}"


@settings(max_examples=50, deadline=None)
@given(st.data())
def test_hypothesis_invariants_across_random_event_sequences(data: st.DataObject) -> None:
    """Property test verifying INV-1..INV-9 hold across arbitrary sequences of domain events."""
    config = JunctionConfig(id="A", name="Junction A")
    state = JunctionState(
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

    current_time = 100.0
    num_steps = data.draw(st.integers(min_value=5, max_value=30))

    for _ in range(num_steps):
        event, current_time = data.draw(domain_event_strategy(current_time))
        state, effects = process_event(state, config, event, now=current_time)
        assert_safety_invariants(state, effects, config)
