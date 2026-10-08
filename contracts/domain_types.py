"""Domain types and data contracts for Factory Traffic Management System.

Shared dataclasses and enums frozen at Gate 1.
Reference: Instruction.md section 5.1 and Decision.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Direction(StrEnum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class Phase(StrEnum):
    NS = "NS"
    EW = "EW"


class Signal(StrEnum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    UNKNOWN = "UNKNOWN"


class Mode(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    DEGRADED = "DEGRADED"


class VehicleType(StrEnum):
    EMERGENCY = "EMERGENCY"
    TRUCK = "TRUCK"
    FORKLIFT = "FORKLIFT"
    EMPLOYEE_VEHICLE = "EMPLOYEE_VEHICLE"


class Step(StrEnum):
    BOOT = "BOOT"
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ALL_RED = "ALL_RED"


class CommandStatus(StrEnum):
    PENDING = "PENDING"
    ACKED = "ACKED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


# Alert types (Instruction.md 5.3)
ALERT_CONTROLLER_OFFLINE = "CONTROLLER_OFFLINE"
ALERT_SIGNAL_FAILURE = "SIGNAL_FAILURE"
ALERT_SENSOR_FAILURE = "SENSOR_FAILURE"
ALERT_STATE_MISMATCH = "STATE_MISMATCH"
ALERT_COMMAND_TIMEOUT = "COMMAND_TIMEOUT"
ALERT_UNKNOWN_DEVICE_STATE = "UNKNOWN_DEVICE_STATE"


@dataclass(slots=True)
class TimingsConfig:
    green: float = 30.0  # D-07
    yellow: float = 5.0  # D-07
    all_red: float = 2.0  # D-07, S-6
    min_green: float = 10.0  # D-07
    max_green: float = 60.0  # D-07
    ack_timeout: float = 3.0  # D-19, P-03
    max_retries: int = 2  # D-19
    starvation_after: float = 90.0  # D-09
    emergency_timeout: float = 120.0  # D-17
    manual_lease: float = 300.0  # D-18 (5 minutes)
    stale_event_after: float = 300.0  # D-12 (5 minutes)


@dataclass(slots=True)
class JunctionConfig:
    id: str
    name: str
    phases: dict[Phase, list[Direction]] = field(
        default_factory=lambda: {
            Phase.NS: [Direction.NORTH, Direction.SOUTH],
            Phase.EW: [Direction.EAST, Direction.WEST],
        }
    )
    timings: TimingsConfig = field(default_factory=TimingsConfig)
    vehicle_weights: dict[VehicleType, int] = field(
        default_factory=lambda: {
            VehicleType.TRUCK: 3,
            VehicleType.FORKLIFT: 2,
            VehicleType.EMPLOYEE_VEHICLE: 1,
            VehicleType.EMERGENCY: 0,
        }
    )


@dataclass(slots=True)
class ManualState:
    active: bool = False
    lease_expires_at: float | None = None
    target_phase: Phase | None = None
    issued_by: str | None = None


@dataclass(slots=True)
class EmergencyRecord:
    vehicle_id: str
    direction: Direction
    phase: Phase
    detected_at: float
    expires_at: float


@dataclass(slots=True)
class WaitingVehicle:
    vehicle_id: str
    direction: Direction
    vehicle_type: VehicleType
    arrived_at: float
    sequence_no: int


@dataclass(slots=True)
class JunctionState:
    version: int = 1
    mode: Mode = Mode.AUTOMATIC
    serving: Phase = Phase.NS
    step: Step = Step.BOOT
    target: Phase | None = None
    deadline_at: float | None = None
    desired: dict[Direction, Signal] = field(
        default_factory=lambda: {
            Direction.NORTH: Signal.RED,
            Direction.SOUTH: Signal.RED,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        }
    )
    actual: dict[Direction, Signal] = field(
        default_factory=lambda: {
            Direction.NORTH: Signal.UNKNOWN,
            Direction.SOUTH: Signal.UNKNOWN,
            Direction.EAST: Signal.UNKNOWN,
            Direction.WEST: Signal.UNKNOWN,
        }
    )
    pending_command_ids: list[str] = field(default_factory=list)
    manual: ManualState = field(default_factory=ManualState)
    emergencies: list[EmergencyRecord] = field(default_factory=list)
    waiting_vehicles: list[WaitingVehicle] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
