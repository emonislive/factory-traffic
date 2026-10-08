"""Domain event definitions (inputs to the traffic engine).

Reference: Instruction.md section 5.1 and Decision.md.
Pure data definitions with no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.types import Direction, Phase, Signal, VehicleType


@dataclass(slots=True)
class VehicleArrived:
    event_id: str
    junction_id: str
    direction: Direction
    vehicle_id: str
    vehicle_type: VehicleType
    sensor_time: float
    server_time: float
    sequence_no: int


@dataclass(slots=True)
class VehicleCleared:
    event_id: str
    junction_id: str
    direction: Direction
    vehicle_id: str
    sensor_time: float
    server_time: float
    sequence_no: int


@dataclass(slots=True)
class AdminCommand:
    junction_id: str
    command_type: str  # "MANUAL_GREEN_REQUEST" | "RETURN_TO_AUTOMATIC"
    target_phase: Phase | None
    issued_by: str
    server_time: float


@dataclass(slots=True)
class ControllerAck:
    command_id: str
    junction_id: str
    direction: Direction
    confirmed_state: Signal
    server_time: float


@dataclass(slots=True)
class ControllerNack:
    command_id: str
    junction_id: str
    direction: Direction
    reason: str
    server_time: float


@dataclass(slots=True)
class DeviceStatusChanged:
    junction_id: str
    device_type: str  # "SIGNAL_CONTROLLER" | "SENSOR"
    direction: Direction | None
    status: str  # "ONLINE" | "OFFLINE" | "DEGRADED" | "WARNING" | "UNKNOWN"
    server_time: float


@dataclass(slots=True)
class Tick:
    junction_id: str
    server_time: float


@dataclass(slots=True)
class Boot:
    junction_id: str
    server_time: float
