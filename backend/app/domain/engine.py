"""Pure domain traffic engine (state machine in Instruction.md 5.2, D-02).

Engine signature: (state, event, now) -> (new_state, effects).
No I/O, no DB, no HTTP, no datetime.now().
Owned by Agent A (Phase 1).
"""

from __future__ import annotations

from typing import Any

from app.domain.effects import (
    Alert,
    DomainEffect,
    RecordAudit,
    SendSignalCommand,
)
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
from app.domain.scoring import select_next_phase
from app.domain.types import (
    ALERT_CONTROLLER_OFFLINE,
    ALERT_SENSOR_FAILURE,
    ALERT_SIGNAL_FAILURE,
    ALERT_UNKNOWN_DEVICE_STATE,
    Direction,
    EmergencyRecord,
    JunctionConfig,
    JunctionState,
    ManualState,
    Mode,
    Phase,
    Signal,
    Step,
    VehicleType,
    WaitingVehicle,
)


def _make_command_id(junction_id: str, version: int, direction: Direction, signal: Signal) -> str:
    """Generate deterministic domain command ID for signal transition."""
    return f"cmd-{junction_id}-{version}-{direction.value.lower()}-{signal.value.lower()}"


def _get_phase_for_direction(direction: Direction, config: JunctionConfig) -> Phase:
    """Find which phase contains the specified direction."""
    for phase, dirs in config.phases.items():
        if direction in dirs:
            return phase
    return Phase.NS if direction in (Direction.NORTH, Direction.SOUTH) else Phase.EW


def _get_opposing_phase(phase: Phase) -> Phase:
    """Return the conflicting phase."""
    return Phase.EW if phase == Phase.NS else Phase.NS


def _clone_state(state: JunctionState) -> JunctionState:
    """Create a clean copy of JunctionState with deep-copied collections."""
    return JunctionState(
        version=state.version,
        mode=state.mode,
        serving=state.serving,
        step=state.step,
        target=state.target,
        deadline_at=state.deadline_at,
        desired=dict(state.desired),
        actual=dict(state.actual),
        pending_command_ids=list(state.pending_command_ids),
        manual=ManualState(
            active=state.manual.active,
            lease_expires_at=state.manual.lease_expires_at,
            target_phase=state.manual.target_phase,
            issued_by=state.manual.issued_by,
        ),
        emergencies=[
            EmergencyRecord(
                vehicle_id=e.vehicle_id,
                direction=e.direction,
                phase=e.phase,
                detected_at=e.detected_at,
                expires_at=e.expires_at,
            )
            for e in state.emergencies
        ],
        waiting_vehicles=[
            WaitingVehicle(
                vehicle_id=v.vehicle_id,
                direction=v.direction,
                vehicle_type=v.vehicle_type,
                arrived_at=v.arrived_at,
                sequence_no=v.sequence_no,
            )
            for v in state.waiting_vehicles
        ],
        alerts=list(state.alerts),
    )


def process_event(
    state: JunctionState,
    config: JunctionConfig,
    event: Any,
    now: float,
) -> tuple[JunctionState, list[DomainEffect]]:
    """Transition junction state given an incoming event and return effects.

    Pure function adhering to D-02:
    - No I/O, no DB, no system clocks.
    - Deterministic state machine honoring INV-1 through INV-9.
    """
    new_state = _clone_state(state)
    effects: list[DomainEffect] = []

    # 1. VehicleArrived
    if isinstance(event, VehicleArrived):
        if event.junction_id != config.id:
            effects.append(
                Alert(
                    alert_type=ALERT_UNKNOWN_DEVICE_STATE,
                    message=f"Event junction mismatch: {event.junction_id} != {config.id}",
                )
            )
            return state, effects

        # Stale event check (D-12)
        if abs(event.server_time - event.sensor_time) > config.timings.stale_event_after:
            effects.append(
                RecordAudit(
                    event_type="STALE_SENSOR_EVENT",
                    direction=event.direction,
                    reason=(
                        f"Sensor time {event.sensor_time} differs from server time "
                        f"{event.server_time} by > {config.timings.stale_event_after}s"
                    ),
                    payload={"event_id": event.event_id, "vehicle_id": event.vehicle_id},
                )
            )
            return state, effects

        # Duplicate vehicle arrival check (INV-6, P-01)
        if any(v.vehicle_id == event.vehicle_id for v in state.waiting_vehicles):
            effects.append(
                RecordAudit(
                    event_type="DUPLICATE_SENSOR_EVENT",
                    direction=event.direction,
                    reason=f"Vehicle {event.vehicle_id} is already in waiting queue",
                    payload={"event_id": event.event_id, "vehicle_id": event.vehicle_id},
                )
            )
            return state, effects

        # Emergency vehicle arrival (D-15, D-16, D-17, INV-3, INV-4)
        if event.vehicle_type == VehicleType.EMERGENCY:
            target_phase = _get_phase_for_direction(event.direction, config)

            # Record emergency if not present
            if not any(e.vehicle_id == event.vehicle_id for e in new_state.emergencies):
                new_state.emergencies.append(
                    EmergencyRecord(
                        vehicle_id=event.vehicle_id,
                        direction=event.direction,
                        phase=target_phase,
                        detected_at=now,
                        expires_at=now + config.timings.emergency_timeout,
                    )
                )

            # Add to waiting vehicles for queue tracking / restart recovery (D-20)
            new_state.waiting_vehicles.append(
                WaitingVehicle(
                    vehicle_id=event.vehicle_id,
                    direction=event.direction,
                    vehicle_type=VehicleType.EMERGENCY,
                    arrived_at=now,
                    sequence_no=event.sequence_no,
                )
            )

            effects.append(
                RecordAudit(
                    event_type="EMERGENCY_DETECTED",
                    direction=event.direction,
                    payload={
                        "vehicle_id": event.vehicle_id,
                        "phase": target_phase.value,
                        "expires_at": now + config.timings.emergency_timeout,
                    },
                )
            )

            # In DEGRADED mode, emergencies are recorded but cause no signal changes (INV-9, P-04)
            if new_state.mode == Mode.DEGRADED:
                new_state.version += 1
                return new_state, effects

            # Mode transitions to EMERGENCY (D-15: overrides manual and automatic)
            new_state.mode = Mode.EMERGENCY
            # D-15: Emergency overrides manual; returning to automatic later requires re-issuing
            new_state.manual = ManualState(active=False)

            # D-16: First come first served by server time - determine primary emergency phase
            primary_em_phase = (
                new_state.emergencies[0].phase if new_state.emergencies else target_phase
            )

            # Preemption logic:
            if new_state.serving == target_phase:
                # Already serving emergency phase
                if new_state.step == Step.GREEN:
                    new_state.target = None
                    new_state.version += 1
                    return new_state, effects
                # If currently transitioning to target_phase, keep target
                if new_state.target == target_phase:
                    new_state.version += 1
                    return new_state, effects

            # Serving conflicting phase
            # D-16: First come first served - an active emergency phase is not preempted
            serving_has_active_emergency = any(
                e.phase == new_state.serving
                and now < e.expires_at
                and e.vehicle_id != event.vehicle_id
                for e in new_state.emergencies
            )
            if serving_has_active_emergency:
                # Do not preempt active serving emergency; serve conflicting next
                new_state.target = target_phase
                new_state.version += 1
                return new_state, effects

            # Preempt current phase safely (INV-3, INV-4, D-15, Instruction 5.2)
            if new_state.step == Step.GREEN:
                # Step 1: Initiate transition to YELLOW for serving phase
                new_state.step = Step.YELLOW
                new_state.target = primary_em_phase
                new_state.deadline_at = None  # Wait for all ACKs (D-08, 5.2)

                serving_dirs = config.phases[new_state.serving]
                for d in serving_dirs:
                    new_state.desired[d] = Signal.YELLOW
                    cmd_id = _make_command_id(config.id, new_state.version + 1, d, Signal.YELLOW)
                    new_state.pending_command_ids.append(cmd_id)
                    effects.append(
                        SendSignalCommand(
                            command_id=cmd_id,
                            direction=d,
                            requested_state=Signal.YELLOW,
                        )
                    )

                effects.append(
                    RecordAudit(
                        event_type="SIGNAL_TRANSITION_STARTED",
                        previous_state=Signal.GREEN,
                        new_state=Signal.YELLOW,
                        reason="Emergency preemption initiated",
                        payload={
                            "target_phase": primary_em_phase.value,
                            "vehicle_id": event.vehicle_id,
                        },
                    )
                )
                new_state.version += 1
                return new_state, effects

            elif new_state.step in (Step.YELLOW, Step.ALL_RED, Step.BOOT):
                # If GREEN commands have already been issued to hardware in ALL_RED,
                # do not overwrite target; target will complete and then transition to emergency.
                green_already_commanded = (
                    new_state.step == Step.ALL_RED
                    and new_state.target is not None
                    and any(
                        new_state.desired.get(d) == Signal.GREEN
                        for d in config.phases[new_state.target]
                    )
                )
                if not green_already_commanded:
                    # In transition: direct target to primary emergency phase (D-16 FCFS)
                    new_state.target = primary_em_phase
                new_state.version += 1
                return new_state, effects

        # Normal vehicle arrival
        new_state.waiting_vehicles.append(
            WaitingVehicle(
                vehicle_id=event.vehicle_id,
                direction=event.direction,
                vehicle_type=event.vehicle_type,
                arrived_at=now,
                sequence_no=event.sequence_no,
            )
        )
        effects.append(
            RecordAudit(
                event_type="VEHICLE_ARRIVED",
                direction=event.direction,
                payload={
                    "vehicle_id": event.vehicle_id,
                    "vehicle_type": event.vehicle_type.value,
                    "queue_size": sum(
                        1 for v in new_state.waiting_vehicles if v.direction == event.direction
                    ),
                },
            )
        )
        new_state.version += 1
        return new_state, effects

    # 2. VehicleCleared
    elif isinstance(event, VehicleCleared):
        if event.junction_id != config.id:
            return state, effects

        # Stale check (D-12)
        if abs(event.server_time - event.sensor_time) > config.timings.stale_event_after:
            effects.append(
                RecordAudit(
                    event_type="STALE_SENSOR_EVENT",
                    direction=event.direction,
                    reason="Cleared event timestamp stale (> 5m)",
                    payload={"event_id": event.event_id, "vehicle_id": event.vehicle_id},
                )
            )
            return state, effects

        # Clear from waiting queue (D-03, P-01)
        found_idx = next(
            (
                i
                for i, v in enumerate(new_state.waiting_vehicles)
                if v.vehicle_id == event.vehicle_id
            ),
            None,
        )
        if found_idx is not None:
            new_state.waiting_vehicles.pop(found_idx)
            effects.append(
                RecordAudit(
                    event_type="VEHICLE_CLEARED",
                    direction=event.direction,
                    payload={"vehicle_id": event.vehicle_id},
                )
            )
        else:
            # Orphan clear (D-13, P-01): vehicle not currently waiting
            effects.append(
                RecordAudit(
                    event_type="ORPHAN_CLEARED",
                    direction=event.direction,
                    reason="Vehicle cleared without active waiting record",
                    payload={"vehicle_id": event.vehicle_id},
                )
            )

        # Clear from emergencies if applicable (D-17)
        em_idx = next(
            (i for i, e in enumerate(new_state.emergencies) if e.vehicle_id == event.vehicle_id),
            None,
        )
        if em_idx is not None:
            new_state.emergencies.pop(em_idx)
            effects.append(
                RecordAudit(
                    event_type="EMERGENCY_CLEARED",
                    direction=event.direction,
                    payload={"vehicle_id": event.vehicle_id},
                )
            )
            if not new_state.emergencies and new_state.mode == Mode.EMERGENCY:
                new_state.mode = Mode.AUTOMATIC
                new_state.manual = ManualState(active=False)
                effects.append(
                    RecordAudit(
                        event_type="MODE_CHANGED",
                        reason="All emergencies cleared, returned to AUTOMATIC",
                        payload={"mode": Mode.AUTOMATIC.value},
                    )
                )
            elif new_state.emergencies and new_state.mode == Mode.EMERGENCY:
                # Service next queued emergency if current serving phase is conflicting
                next_em_phase = new_state.emergencies[0].phase
                if next_em_phase != new_state.serving and new_state.step == Step.GREEN:
                    new_state.step = Step.YELLOW
                    new_state.target = next_em_phase
                    new_state.deadline_at = None
                    serving_dirs = config.phases[new_state.serving]
                    for d in serving_dirs:
                        new_state.desired[d] = Signal.YELLOW
                        cmd_id = _make_command_id(
                            config.id, new_state.version + 1, d, Signal.YELLOW
                        )
                        new_state.pending_command_ids.append(cmd_id)
                        effects.append(
                            SendSignalCommand(
                                command_id=cmd_id,
                                direction=d,
                                requested_state=Signal.YELLOW,
                            )
                        )
                    effects.append(
                        RecordAudit(
                            event_type="SIGNAL_TRANSITION_STARTED",
                            previous_state=Signal.GREEN,
                            new_state=Signal.YELLOW,
                            reason=(
                                f"Emergency cleared; transitioning to next emergency on "
                                f"{next_em_phase.value}"
                            ),
                            payload={"target_phase": next_em_phase.value},
                        )
                    )

        new_state.version += 1
        return new_state, effects

    # 3. AdminCommand
    elif isinstance(event, AdminCommand):
        if event.junction_id != config.id:
            return state, effects

        if new_state.mode == Mode.DEGRADED:
            if event.command_type == "RETURN_TO_AUTOMATIC":
                new_state.manual = ManualState(active=False)
                effects.append(
                    RecordAudit(
                        event_type="RETURN_TO_AUTOMATIC_ACCEPTED",
                        reason="Accepted while DEGRADED; no signal action taken per P-04",
                        payload={"issued_by": event.issued_by},
                    )
                )
                new_state.version += 1
                return new_state, effects
            effects.append(
                RecordAudit(
                    event_type="COMMAND_REJECTED",
                    reason="Junction is DEGRADED",
                    payload={"command_type": event.command_type, "issued_by": event.issued_by},
                )
            )
            return state, effects

        if event.command_type == "MANUAL_GREEN_REQUEST":
            if event.target_phase is None:
                return state, effects

            # D-15: Emergency overrides manual (manual commands cannot override active emergency)
            if new_state.mode == Mode.EMERGENCY:
                effects.append(
                    RecordAudit(
                        event_type="COMMAND_REJECTED",
                        reason="Emergency mode active; manual override rejected per D-15",
                        payload={
                            "target_phase": event.target_phase.value,
                            "issued_by": event.issued_by,
                        },
                    )
                )
                return state, effects

            new_state.mode = Mode.MANUAL
            new_state.manual = ManualState(
                active=True,
                lease_expires_at=now + config.timings.manual_lease,
                target_phase=event.target_phase,
                issued_by=event.issued_by,
            )
            effects.append(
                RecordAudit(
                    event_type="MANUAL_OVERRIDE_ACTIVATED",
                    payload={
                        "target_phase": event.target_phase.value,
                        "issued_by": event.issued_by,
                        "lease_expires_at": new_state.manual.lease_expires_at,
                    },
                )
            )

            if event.target_phase != new_state.serving:
                if new_state.step == Step.GREEN:
                    new_state.step = Step.YELLOW
                    new_state.target = event.target_phase
                    new_state.deadline_at = None

                    serving_dirs = config.phases[new_state.serving]
                    for d in serving_dirs:
                        new_state.desired[d] = Signal.YELLOW
                        cmd_id = _make_command_id(
                            config.id, new_state.version + 1, d, Signal.YELLOW
                        )
                        new_state.pending_command_ids.append(cmd_id)
                        effects.append(
                            SendSignalCommand(
                                command_id=cmd_id,
                                direction=d,
                                requested_state=Signal.YELLOW,
                            )
                        )

                    effects.append(
                        RecordAudit(
                            event_type="SIGNAL_TRANSITION_STARTED",
                            previous_state=Signal.GREEN,
                            new_state=Signal.YELLOW,
                            reason="Manual green request initiated",
                            payload={"target_phase": event.target_phase.value},
                        )
                    )
                elif new_state.step in (Step.YELLOW, Step.ALL_RED, Step.BOOT):
                    green_already_commanded = (
                        new_state.step == Step.ALL_RED
                        and new_state.target is not None
                        and any(
                            new_state.desired.get(d) == Signal.GREEN
                            for d in config.phases[new_state.target]
                        )
                    )
                    if not green_already_commanded:
                        new_state.target = event.target_phase

            new_state.version += 1
            return new_state, effects

        elif event.command_type == "RETURN_TO_AUTOMATIC":
            new_state.manual = ManualState(active=False)
            if new_state.mode == Mode.MANUAL:
                new_state.mode = Mode.AUTOMATIC
                effects.append(
                    RecordAudit(
                        event_type="RETURN_TO_AUTOMATIC",
                        payload={"issued_by": event.issued_by},
                    )
                )
            new_state.version += 1
            return new_state, effects

    # 4. ControllerAck
    elif isinstance(event, ControllerAck):
        if event.junction_id != config.id:
            return state, effects

        # Check if ACK matches an outstanding pending command (D-19)
        if event.command_id not in new_state.pending_command_ids:
            if event.direction in new_state.actual:
                new_state.actual[event.direction] = event.confirmed_state
            effects.append(
                RecordAudit(
                    event_type="CONTROLLER_ACK_UNTRACKED",
                    command_id=event.command_id,
                    direction=event.direction,
                    new_state=event.confirmed_state,
                    reason="Command ID not in pending commands (duplicate or late ACK)",
                )
            )
            return state, effects

        new_state.pending_command_ids.remove(event.command_id)
        new_state.actual[event.direction] = event.confirmed_state
        effects.append(
            RecordAudit(
                event_type="SIGNAL_STATE_CONFIRMED",
                command_id=event.command_id,
                direction=event.direction,
                new_state=event.confirmed_state,
            )
        )

        serving_dirs = config.phases[new_state.serving]

        # Step progression on confirmation (Instruction.md 5.2):
        if new_state.step == Step.YELLOW:
            # 1 -> 2: If all serving directions confirmed YELLOW, start yellow hold deadline
            if all(new_state.desired[d] == Signal.YELLOW for d in serving_dirs) and all(
                new_state.actual.get(d) == Signal.YELLOW for d in serving_dirs
            ):
                new_state.deadline_at = now + config.timings.yellow
                effects.append(
                    RecordAudit(
                        event_type="STEP_DEADLINE_SET",
                        reason="All YELLOW ACKs received, yellow hold timer started",
                        payload={"deadline_at": new_state.deadline_at},
                    )
                )
            # 3 -> 4: If desired was RED and all serving directions confirmed RED, enter ALL_RED
            elif all(new_state.desired[d] == Signal.RED for d in serving_dirs) and all(
                new_state.actual.get(d) == Signal.RED for d in serving_dirs
            ):
                new_state.step = Step.ALL_RED
                new_state.deadline_at = now + config.timings.all_red
                effects.append(
                    RecordAudit(
                        event_type="SIGNAL_TRANSITION_STEP",
                        previous_state=Signal.YELLOW,
                        new_state=Signal.RED,
                        reason="All RED ACKs received, entered ALL_RED step",
                        payload={"deadline_at": new_state.deadline_at},
                    )
                )

        elif new_state.step == Step.ALL_RED and new_state.target is not None:
            target_dirs = config.phases[new_state.target]
            # 5 -> 6: If desired was GREEN and all target directions confirmed GREEN, enter GREEN
            if all(new_state.desired[d] == Signal.GREEN for d in target_dirs) and all(
                new_state.actual.get(d) == Signal.GREEN for d in target_dirs
            ):
                new_state.step = Step.GREEN
                new_state.serving = new_state.target
                new_state.target = None
                new_state.deadline_at = now + config.timings.green
                effects.append(
                    RecordAudit(
                        event_type="SIGNAL_TRANSITION_COMPLETED",
                        previous_state=Signal.RED,
                        new_state=Signal.GREEN,
                        reason=f"All GREEN ACKs received, now serving {new_state.serving.value}",
                        payload={
                            "serving": new_state.serving.value,
                            "deadline_at": new_state.deadline_at,
                        },
                    )
                )

                # Check if an active emergency on a conflicting phase is queued (D-15, D-16)
                if (
                    new_state.mode == Mode.EMERGENCY
                    and new_state.emergencies
                    and new_state.emergencies[0].phase != new_state.serving
                ):
                    em_target = new_state.emergencies[0].phase
                    new_state.step = Step.YELLOW
                    new_state.target = em_target
                    new_state.deadline_at = None
                    serving_dirs = config.phases[new_state.serving]
                    for d in serving_dirs:
                        new_state.desired[d] = Signal.YELLOW
                        cmd_id = _make_command_id(
                            config.id, new_state.version + 1, d, Signal.YELLOW
                        )
                        new_state.pending_command_ids.append(cmd_id)
                        effects.append(
                            SendSignalCommand(
                                command_id=cmd_id,
                                direction=d,
                                requested_state=Signal.YELLOW,
                            )
                        )
                    effects.append(
                        RecordAudit(
                            event_type="SIGNAL_TRANSITION_STARTED",
                            previous_state=Signal.GREEN,
                            new_state=Signal.YELLOW,
                            reason=(
                                "Queued conflicting emergency preemption initiated "
                                "upon green confirmation"
                            ),
                            payload={"target_phase": em_target.value},
                        )
                    )

        elif new_state.step == Step.BOOT:
            all_dirs = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
            if all(new_state.actual.get(d) == Signal.RED for d in all_dirs):
                new_state.step = Step.ALL_RED
                new_state.deadline_at = now + config.timings.all_red
                new_state.target = None
                # Clear recovery alerts
                if ALERT_CONTROLLER_OFFLINE in new_state.alerts:
                    new_state.alerts.remove(ALERT_CONTROLLER_OFFLINE)
                if ALERT_SIGNAL_FAILURE in new_state.alerts:
                    new_state.alerts.remove(ALERT_SIGNAL_FAILURE)
                if new_state.mode == Mode.DEGRADED:
                    if new_state.emergencies:
                        new_state.mode = Mode.EMERGENCY
                    elif new_state.manual.active and (
                        new_state.manual.lease_expires_at is None
                        or now < new_state.manual.lease_expires_at
                    ):
                        new_state.mode = Mode.MANUAL
                    else:
                        new_state.mode = Mode.AUTOMATIC
                effects.append(
                    RecordAudit(
                        event_type="BOOT_ALL_RED_CONFIRMED",
                        reason="Boot ALL_RED confirmed by controller",
                        payload={"deadline_at": new_state.deadline_at},
                    )
                )

        new_state.version += 1
        return new_state, effects

    # 5. ControllerNack
    elif isinstance(event, ControllerNack):
        if event.junction_id != config.id:
            return state, effects

        # Controller failed command (D-19, INV-9)
        new_state.mode = Mode.DEGRADED
        if ALERT_SIGNAL_FAILURE not in new_state.alerts:
            new_state.alerts.append(ALERT_SIGNAL_FAILURE)
        effects.append(
            Alert(
                alert_type=ALERT_SIGNAL_FAILURE,
                message=f"Controller NACK on {event.direction}: {event.reason}",
                details={"command_id": event.command_id, "direction": event.direction.value},
            )
        )
        # Fail-safe (D-19, INV-7): actual=UNKNOWN and request ALL_RED
        for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
            new_state.actual[d] = Signal.UNKNOWN
            new_state.desired[d] = Signal.RED
        new_state.pending_command_ids.clear()
        new_state.target = None
        new_state.deadline_at = None
        new_state.step = Step.BOOT  # await confirmation of ALL_RED fail-safe
        for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
            cmd_id = _make_command_id(config.id, new_state.version + 1, d, Signal.RED)
            new_state.pending_command_ids.append(cmd_id)
            effects.append(
                SendSignalCommand(command_id=cmd_id, direction=d, requested_state=Signal.RED)
            )

        new_state.version += 1
        return new_state, effects

    # 6. DeviceStatusChanged
    elif isinstance(event, DeviceStatusChanged):
        if event.junction_id != config.id:
            return state, effects

        if event.device_type == "SIGNAL_CONTROLLER":
            if event.status == "OFFLINE":
                new_state.mode = Mode.DEGRADED
                if ALERT_CONTROLLER_OFFLINE not in new_state.alerts:
                    new_state.alerts.append(ALERT_CONTROLLER_OFFLINE)
                for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
                    new_state.actual[d] = Signal.UNKNOWN
                    new_state.desired[d] = Signal.RED
                new_state.pending_command_ids.clear()
                new_state.target = None
                new_state.deadline_at = None
                effects.append(
                    Alert(
                        alert_type=ALERT_CONTROLLER_OFFLINE,
                        message="Signal controller went OFFLINE. Human traffic marshal required.",
                    )
                )
            elif event.status == "ONLINE":
                # D-19: Controller reconnect: stay DEGRADED until actual state is confirmed,
                # then restart from ALL_RED.
                if new_state.mode == Mode.DEGRADED:
                    new_state.step = Step.BOOT
                    new_state.target = None
                    new_state.deadline_at = None
                    new_state.pending_command_ids.clear()
                    for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
                        new_state.actual[d] = Signal.UNKNOWN
                        new_state.desired[d] = Signal.RED
                        cmd_id = _make_command_id(config.id, new_state.version + 1, d, Signal.RED)
                        new_state.pending_command_ids.append(cmd_id)
                        effects.append(
                            SendSignalCommand(
                                command_id=cmd_id, direction=d, requested_state=Signal.RED
                            )
                        )
                    effects.append(
                        RecordAudit(
                            event_type="CONTROLLER_RECONNECT_RESTART",
                            reason=(
                                "Controller reconnected; requested ALL_RED confirmation to recover"
                            ),
                        )
                    )
                else:
                    if ALERT_CONTROLLER_OFFLINE in new_state.alerts:
                        new_state.alerts.remove(ALERT_CONTROLLER_OFFLINE)
                    effects.append(
                        RecordAudit(
                            event_type="CONTROLLER_ONLINE",
                            reason="Controller online; awaiting state confirmation",
                        )
                    )

        elif event.device_type == "SENSOR":
            if event.status == "OFFLINE":
                if ALERT_SENSOR_FAILURE not in new_state.alerts:
                    new_state.alerts.append(ALERT_SENSOR_FAILURE)
                effects.append(
                    Alert(
                        alert_type=ALERT_SENSOR_FAILURE,
                        message=f"Sensor for {event.direction} OFFLINE",
                        details={"direction": event.direction.value if event.direction else None},
                    )
                )

        new_state.version += 1
        return new_state, effects

    # 7. Tick
    elif isinstance(event, Tick):
        if event.junction_id != config.id:
            return state, effects

        # Clean expired emergencies (D-17)
        active_emergencies: list[EmergencyRecord] = []
        for e in new_state.emergencies:
            if now >= e.expires_at:
                effects.append(
                    RecordAudit(
                        event_type="EMERGENCY_TIMEOUT",
                        direction=e.direction,
                        reason=(
                            f"Emergency {e.vehicle_id} expired after "
                            f"{config.timings.emergency_timeout}s"
                        ),
                        payload={"vehicle_id": e.vehicle_id},
                    )
                )
            else:
                active_emergencies.append(e)
        new_state.emergencies = active_emergencies

        # Prune expired emergency from waiting queue
        active_em_ids = {e.vehicle_id for e in active_emergencies}
        new_state.waiting_vehicles = [
            v
            for v in new_state.waiting_vehicles
            if v.vehicle_type != VehicleType.EMERGENCY or v.vehicle_id in active_em_ids
        ]

        if new_state.mode == Mode.EMERGENCY and not new_state.emergencies:
            new_state.mode = Mode.AUTOMATIC
            new_state.manual = ManualState(active=False)  # D-15
            effects.append(
                RecordAudit(
                    event_type="MODE_CHANGED",
                    reason="All emergencies timed out, returned to AUTOMATIC",
                    payload={"mode": Mode.AUTOMATIC.value},
                )
            )

        # Expired manual lease (D-18)
        if new_state.mode == Mode.MANUAL and new_state.manual.active:
            if (
                new_state.manual.lease_expires_at is not None
                and now >= new_state.manual.lease_expires_at
            ):
                new_state.manual.active = False
                new_state.mode = Mode.AUTOMATIC
                effects.append(
                    RecordAudit(
                        event_type="MANUAL_LEASE_EXPIRED",
                        reason="Manual lease expired, returned to AUTOMATIC",
                    )
                )

        # In DEGRADED mode, no GREEN transitions occur (INV-9)
        if new_state.mode == Mode.DEGRADED:
            return new_state, effects

        serving_dirs = config.phases[new_state.serving]

        # Transition Step 3: YELLOW hold deadline elapsed -> emit RED for serving phase
        if new_state.step == Step.YELLOW:
            if all(new_state.desired[d] == Signal.YELLOW for d in serving_dirs):
                if new_state.deadline_at is not None and now >= new_state.deadline_at:
                    for d in serving_dirs:
                        new_state.desired[d] = Signal.RED
                        cmd_id = _make_command_id(config.id, new_state.version + 1, d, Signal.RED)
                        new_state.pending_command_ids.append(cmd_id)
                        effects.append(
                            SendSignalCommand(
                                command_id=cmd_id,
                                direction=d,
                                requested_state=Signal.RED,
                            )
                        )
                    new_state.deadline_at = None  # Wait for RED ACKs
                    effects.append(
                        RecordAudit(
                            event_type="SIGNAL_TRANSITION_STEP",
                            previous_state=Signal.YELLOW,
                            new_state=Signal.RED,
                            reason=(
                                f"Yellow duration elapsed, requested RED for "
                                f"{new_state.serving.value}"
                            ),
                        )
                    )
                    new_state.version += 1
                    return new_state, effects

        # Transition Step 5: ALL_RED hold deadline elapsed -> emit GREEN for target phase
        elif new_state.step == Step.ALL_RED:
            target = new_state.target
            if target is None:
                if new_state.mode == Mode.EMERGENCY and new_state.emergencies:
                    target = new_state.emergencies[0].phase
                elif (
                    new_state.mode == Mode.MANUAL
                    and new_state.manual.active
                    and new_state.manual.target_phase
                ):
                    target = new_state.manual.target_phase
                else:
                    target = select_next_phase(new_state, config, now)
                new_state.target = target

            if new_state.target is not None:
                if new_state.deadline_at is not None and now >= new_state.deadline_at:
                    # INV-2, D-08: Check that opposing directions are CONFIRMED RED
                    opposing_phase = _get_opposing_phase(new_state.target)
                    opposing_dirs = config.phases[opposing_phase]
                    opposing_confirmed_red = all(
                        new_state.actual.get(d) == Signal.RED for d in opposing_dirs
                    )
                    if opposing_confirmed_red:
                        target_dirs = config.phases[new_state.target]
                        for d in target_dirs:
                            new_state.desired[d] = Signal.GREEN
                            cmd_id = _make_command_id(
                                config.id, new_state.version + 1, d, Signal.GREEN
                            )
                            new_state.pending_command_ids.append(cmd_id)
                            effects.append(
                                SendSignalCommand(
                                    command_id=cmd_id,
                                    direction=d,
                                    requested_state=Signal.GREEN,
                                )
                            )
                        new_state.deadline_at = None  # Wait for GREEN ACKs
                        effects.append(
                            RecordAudit(
                                event_type="SIGNAL_TRANSITION_STEP",
                                previous_state=Signal.RED,
                                new_state=Signal.GREEN,
                                reason=(
                                    f"All-red elapsed and opposing RED confirmed, "
                                    f"requested GREEN for {new_state.target.value}"
                                ),
                            )
                        )
                        new_state.version += 1
                        return new_state, effects

        # Step GREEN: check for scheduled transitions or emergency/manual switches
        elif new_state.step == Step.GREEN:
            if new_state.mode == Mode.AUTOMATIC:
                if new_state.deadline_at is not None and now >= new_state.deadline_at:
                    next_phase = select_next_phase(new_state, config, now)
                    if next_phase != new_state.serving:
                        new_state.step = Step.YELLOW
                        new_state.target = next_phase
                        new_state.deadline_at = None
                        for d in serving_dirs:
                            new_state.desired[d] = Signal.YELLOW
                            cmd_id = _make_command_id(
                                config.id, new_state.version + 1, d, Signal.YELLOW
                            )
                            new_state.pending_command_ids.append(cmd_id)
                            effects.append(
                                SendSignalCommand(
                                    command_id=cmd_id,
                                    direction=d,
                                    requested_state=Signal.YELLOW,
                                )
                            )
                        effects.append(
                            RecordAudit(
                                event_type="SIGNAL_TRANSITION_STARTED",
                                previous_state=Signal.GREEN,
                                new_state=Signal.YELLOW,
                                reason=f"Scheduled transition to {next_phase.value}",
                            )
                        )
                        new_state.version += 1
                        return new_state, effects
                    else:
                        # No switch: extend green
                        new_state.deadline_at = now + config.timings.green

            elif new_state.mode == Mode.EMERGENCY:
                if new_state.emergencies:
                    em_phase = new_state.emergencies[0].phase
                    if em_phase != new_state.serving:
                        new_state.step = Step.YELLOW
                        new_state.target = em_phase
                        new_state.deadline_at = None
                        for d in serving_dirs:
                            new_state.desired[d] = Signal.YELLOW
                            cmd_id = _make_command_id(
                                config.id, new_state.version + 1, d, Signal.YELLOW
                            )
                            new_state.pending_command_ids.append(cmd_id)
                            effects.append(
                                SendSignalCommand(
                                    command_id=cmd_id,
                                    direction=d,
                                    requested_state=Signal.YELLOW,
                                )
                            )
                        effects.append(
                            RecordAudit(
                                event_type="SIGNAL_TRANSITION_STARTED",
                                previous_state=Signal.GREEN,
                                new_state=Signal.YELLOW,
                                reason="Emergency preemption initiated on Tick",
                            )
                        )
                        new_state.version += 1
                        return new_state, effects

            elif new_state.mode == Mode.MANUAL:
                if (
                    new_state.manual.active
                    and new_state.manual.target_phase
                    and new_state.manual.target_phase != new_state.serving
                ):
                    new_state.step = Step.YELLOW
                    new_state.target = new_state.manual.target_phase
                    new_state.deadline_at = None
                    for d in serving_dirs:
                        new_state.desired[d] = Signal.YELLOW
                        cmd_id = _make_command_id(
                            config.id, new_state.version + 1, d, Signal.YELLOW
                        )
                        new_state.pending_command_ids.append(cmd_id)
                        effects.append(
                            SendSignalCommand(
                                command_id=cmd_id,
                                direction=d,
                                requested_state=Signal.YELLOW,
                            )
                        )
                    effects.append(
                        RecordAudit(
                            event_type="SIGNAL_TRANSITION_STARTED",
                            previous_state=Signal.GREEN,
                            new_state=Signal.YELLOW,
                            reason="Manual override transition initiated on Tick",
                        )
                    )
                    new_state.version += 1
                    return new_state, effects

        return new_state, effects

    # 8. Boot
    elif isinstance(event, Boot):
        if event.junction_id != config.id:
            return state, effects

        # D-20: Load saved state, actual = UNKNOWN, request ALL_RED from controller
        for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
            new_state.actual[d] = Signal.UNKNOWN
            new_state.desired[d] = Signal.RED

        new_state.pending_command_ids = []
        new_state.step = Step.BOOT
        new_state.target = None
        new_state.deadline_at = None

        # Re-derive emergencies from waiting vehicles with type EMERGENCY (D-20)
        new_state.emergencies = []
        for v in new_state.waiting_vehicles:
            if v.vehicle_type == VehicleType.EMERGENCY:
                phase = _get_phase_for_direction(v.direction, config)
                new_state.emergencies.append(
                    EmergencyRecord(
                        vehicle_id=v.vehicle_id,
                        direction=v.direction,
                        phase=phase,
                        detected_at=now,
                        expires_at=now + config.timings.emergency_timeout,
                    )
                )

        if new_state.emergencies and new_state.mode != Mode.DEGRADED:
            new_state.mode = Mode.EMERGENCY
        elif new_state.mode == Mode.MANUAL:
            if (
                new_state.manual.lease_expires_at is None
                or now >= new_state.manual.lease_expires_at
            ):
                new_state.manual.active = False
                new_state.mode = Mode.AUTOMATIC
        else:
            new_state.mode = Mode.AUTOMATIC

        for d in [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]:
            cmd_id = _make_command_id(config.id, new_state.version + 1, d, Signal.RED)
            new_state.pending_command_ids.append(cmd_id)
            effects.append(
                SendSignalCommand(command_id=cmd_id, direction=d, requested_state=Signal.RED)
            )

        effects.append(
            RecordAudit(
                event_type="BOOT_RECOVERY",
                reason="Boot recovery initialized: actual=UNKNOWN, requested ALL_RED",
            )
        )
        new_state.version += 1
        return new_state, effects

    return state, effects
