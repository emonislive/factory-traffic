"""FastAPI route handlers matching contracts/openapi.yaml.

Owned by Agent B (Phase 1).
"""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    AdminCommandRequest,
    AdminCommandResponse,
    AuditLogEntry,
    ControllerEventRequest,
    ControllerEventResponse,
    CreateJunctionRequest,
    DeviceStatusRequest,
    DeviceStatusResponse,
    JunctionDetail,
    JunctionStatusResponse,
    JunctionSummary,
    SensorEventRequest,
    SensorEventResponse,
    SetSimulatorModeRequest,
    SetSimulatorModeResponse,
)

router = APIRouter(prefix="/api")


@router.get("/junctions", response_model=list[JunctionSummary])
async def list_junctions() -> list[JunctionSummary]:
    return []


@router.post("/junctions", status_code=status.HTTP_201_CREATED, response_model=JunctionDetail)
async def create_junction(req: CreateJunctionRequest) -> JunctionDetail:
    # Stub for Phase 0
    from datetime import datetime
    return JunctionDetail(
        id=req.id,
        name=req.name,
        config=req.model_dump(),
        created_at=datetime.now(UTC),
    )


@router.get("/junctions/{id}", response_model=JunctionDetail)
async def get_junction(id: str) -> JunctionDetail:
    from datetime import datetime
    return JunctionDetail(
        id=id,
        name="Junction " + id,
        config={},
        created_at=datetime.now(UTC),
    )


@router.post(
    "/sensor-events",
    status_code=status.HTTP_201_CREATED,
    response_model=SensorEventResponse,
)
async def ingest_sensor_event(req: SensorEventRequest) -> SensorEventResponse:
    # Stub for Phase 0
    return SensorEventResponse(event_id=req.event_id, status="APPLIED", duplicate=False)


@router.get("/junctions/{id}/status", response_model=JunctionStatusResponse)
async def get_junction_status(id: str) -> JunctionStatusResponse:
    # Stub for Phase 0
    from app.api.schemas import EmergencyStatus, ManualStatus, TransitionStatus
    from app.domain.types import Mode, Signal, Step
    return JunctionStatusResponse(
        junction_id=id,
        mode=Mode.AUTOMATIC,
        phase="NS",
        controller_status="ONLINE",
        desired_signals={
            "NORTH": Signal.RED,
            "SOUTH": Signal.RED,
            "EAST": Signal.RED,
            "WEST": Signal.RED,
        },
        actual_signals={
            "NORTH": Signal.UNKNOWN,
            "SOUTH": Signal.UNKNOWN,
            "EAST": Signal.UNKNOWN,
            "WEST": Signal.UNKNOWN,
        },
        queues={"NORTH": 0, "SOUTH": 0, "EAST": 0, "WEST": 0},
        transition=TransitionStatus(step=Step.BOOT, target=None, deadline_at=None),
        pending_commands=[],
        emergency=EmergencyStatus(active=False, direction=None, vehicle_id=None),
        manual=ManualStatus(active=False, lease_expires_at=None, issued_by=None),
        alerts=[],
        device_statuses={},
        stale_queues=[],
    )


@router.post(
    "/junctions/{id}/commands",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AdminCommandResponse,
)
async def issue_command(id: str, req: AdminCommandRequest) -> AdminCommandResponse:
    # Stub for Phase 0
    return AdminCommandResponse(status="ACCEPTED", message="Command queued")


@router.post("/controller-events", response_model=ControllerEventResponse)
async def ingest_controller_event(req: ControllerEventRequest) -> ControllerEventResponse:
    # Stub for Phase 0
    return ControllerEventResponse(command_id=req.command_id, status="PROCESSED", duplicate=False)


@router.post("/device-status", response_model=DeviceStatusResponse)
async def report_device_status(req: DeviceStatusRequest) -> DeviceStatusResponse:
    # Stub for Phase 0
    return DeviceStatusResponse(event_id=req.event_id, status="UPDATED")


@router.get("/junctions/{id}/history", response_model=list[AuditLogEntry])
async def get_junction_history(
    id: str, limit: int = 50, before_id: int | None = None, event_type: str | None = None
) -> list[AuditLogEntry]:
    return []


@router.get("/junctions/{id}/stream")
async def stream_junction_status(id: str) -> StreamingResponse:
    # Stub for Phase 0
    from collections.abc import AsyncGenerator

    async def dummy_gen() -> AsyncGenerator[str, None]:
        yield ": ping\n\n"

    return StreamingResponse(dummy_gen(), media_type="text/event-stream")


@router.post("/simulator/{id}/mode", response_model=SetSimulatorModeResponse)
async def set_simulator_mode(id: str, req: SetSimulatorModeRequest) -> SetSimulatorModeResponse:
    return SetSimulatorModeResponse(junction_id=id, mode=req.mode)
