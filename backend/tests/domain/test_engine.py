"""Domain engine tests.

Tests for domain engine state transitions, decisions D-07..D-20, and invariants INV-1..INV-9.
"""

from app.domain.effects import SendSignalCommand
from app.domain.engine import process_event
from app.domain.events import VehicleArrived
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


def test_emergency_preemption_initiates_yellow_transition() -> None:
    """INV-3, INV-4, D-15: Emergency on EAST while NS is GREEN initiates transition to YELLOW."""
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
