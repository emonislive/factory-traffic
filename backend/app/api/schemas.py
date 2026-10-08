"""Pydantic v2 schemas matching contracts/openapi.yaml.

Owned by Agent B (Phase 1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.types import Direction, Mode, Signal, Step, VehicleType


class JunctionSummary(BaseModel):
    id: str
    name: str


class TimingsConfigSchema(BaseModel):
    green: float = 30.0
    yellow: float = 5.0
    all_red: float = 2.0
    min_green: float = 10.0
    max_green: float = 60.0
    ack_timeout: float = 3.0
    max_retries: int = 2
    starvation_after: float = 90.0
    emergency_timeout: float = 120.0
    manual_lease: float = 300.0
    stale_event_after: float = 300.0


class CreateJunctionRequest(BaseModel):
    id: str
    name: str
    phases: dict[str, list[Direction]]
    timings: TimingsConfigSchema = Field(default_factory=TimingsConfigSchema)


class JunctionDetail(BaseModel):
    id: str
    name: str
    config: dict[str, Any]
    created_at: datetime


class SensorEventRequest(BaseModel):
    event_id: str
    junction_id: str
    direction: Direction
    event_type: str  # VEHICLE_ARRIVED, VEHICLE_CLEARED
    vehicle_id: str
    vehicle_type: VehicleType | None = None
    sequence_no: int
    timestamp: datetime


class SensorEventResponse(BaseModel):
    event_id: str
    status: str
    duplicate: bool = False
    reason: str | None = None


class TransitionStatus(BaseModel):
    step: Step
    target: str | None = None
    deadline_at: float | None = None


class EmergencyStatus(BaseModel):
    active: bool
    direction: str | None = None
    vehicle_id: str | None = None


class ManualStatus(BaseModel):
    active: bool
    lease_expires_at: float | None = None
    issued_by: str | None = None


class JunctionStatusResponse(BaseModel):
    junction_id: str
    mode: Mode
    phase: str
    controller_status: str
    desired_signals: dict[str, Signal]
    actual_signals: dict[str, Signal]
    queues: dict[str, int]
    transition: TransitionStatus
    pending_commands: list[str]
    emergency: EmergencyStatus
    manual: ManualStatus
    alerts: list[str]
    device_statuses: dict[str, Any]
    stale_queues: list[str]


class AdminCommandRequest(BaseModel):
    command: str  # MANUAL_GREEN_REQUEST, RETURN_TO_AUTOMATIC
    direction: Direction | None = None
    issued_by: str = "anonymous"


class AdminCommandResponse(BaseModel):
    status: str
    message: str


class ControllerEventRequest(BaseModel):
    command_id: str
    junction_id: str
    direction: Direction | None = None
    status: str  # ACK, NACK
    actual_state: Signal | None = None
    reason: str | None = None


class ControllerEventResponse(BaseModel):
    command_id: str
    status: str
    duplicate: bool = False


class DeviceStatusRequest(BaseModel):
    event_id: str
    junction_id: str
    device_type: str
    direction: Direction | None = None
    status: str
    timestamp: datetime


class DeviceStatusResponse(BaseModel):
    event_id: str
    status: str


class AuditLogEntry(BaseModel):
    id: int
    junction_id: str
    event_type: str
    direction: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    command_id: str | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None
    occurred_at: datetime
    source: str


class SetSimulatorModeRequest(BaseModel):
    mode: str


class SetSimulatorModeResponse(BaseModel):
    junction_id: str
    mode: str
