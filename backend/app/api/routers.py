"""FastAPI route handlers matching contracts/openapi.yaml.

Owned by Agent B (Phase 1).
Routers are thin adapters mapping HTTP to junction worker events and back.
Status codes strictly adhere to P-02.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
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
from app.api.sse import sse_event_generator
from app.application.junction_worker import JunctionWorker, get_junction_manager
from app.domain.config import validate_junction_config
from app.domain.events import (
    AdminCommand,
    ControllerAck,
    ControllerNack,
    DeviceStatusChanged,
    VehicleArrived,
    VehicleCleared,
)
from app.domain.types import (
    Direction,
    JunctionConfig,
    Phase,
    Signal,
    TimingsConfig,
)
from app.infrastructure.controllers.rest_simulator import SimulatorMode
from app.infrastructure.db.models import JunctionStateModel
from app.infrastructure.db.repositories import (
    AuditLogRepository,
    JunctionRepository,
)
from app.infrastructure.db.session import get_db_session, get_session_factory

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


async def _get_worker_or_404(junction_id: str) -> JunctionWorker:
    """Helper retrieving worker or verifying junction exists in database."""
    manager = get_junction_manager()
    worker = manager.get_worker(junction_id)
    if worker is not None:
        return worker

    # Worker not in memory: check database
    factory = get_session_factory()
    async with factory() as session:
        repo = JunctionRepository(session)
        j_model = await repo.get(junction_id)
        if j_model is None:
            raise AppError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="JUNCTION_NOT_FOUND",
                message=f"Junction {junction_id} not found.",
                details={"junction_id": junction_id},
            )

        # Restore worker from database config
        cfg_dict = j_model.config
        phases_raw = cfg_dict.get("phases", {})
        phases = {
            Phase(p): [Direction(d) for d in dirs]
            for p, dirs in phases_raw.items()
        }
        timings_raw = cfg_dict.get("timings", {})
        timings = TimingsConfig(**timings_raw) if timings_raw else TimingsConfig()
        config = JunctionConfig(
            id=j_model.id,
            name=j_model.name,
            phases=phases,
            timings=timings,
        )
        worker = manager.register_junction(config)
        await worker.start()
        from app.application.recovery import recover_junction

        await recover_junction(junction_id, worker, factory)
        return worker


@router.get("/junctions", response_model=list[JunctionSummary])
async def list_junctions(
    session: SessionDep,
) -> list[JunctionSummary]:
    repo = JunctionRepository(session)
    junctions = await repo.list_all()
    j_dict = {j.id: j.name for j in junctions}
    manager = get_junction_manager()
    for w in manager.list_workers():
        if w.junction_id not in j_dict:
            j_dict[w.junction_id] = w.config.name
    return [JunctionSummary(id=k, name=v) for k, v in j_dict.items()]


@router.post(
    "/junctions",
    status_code=status.HTTP_201_CREATED,
    response_model=JunctionDetail,
)
async def create_junction(
    req: CreateJunctionRequest,
    session: SessionDep,
) -> JunctionDetail:
    # 1. Build and validate domain config (D-10)
    phases = {
        Phase(p): [Direction(d) for d in dirs]
        for p, dirs in req.phases.items()
    }
    timings = TimingsConfig(**req.timings.model_dump())
    domain_config = JunctionConfig(
        id=req.id,
        name=req.name,
        phases=phases,
        timings=timings,
    )
    try:
        validate_junction_config(domain_config)
    except ValueError as err:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_JUNCTION_CONFIG",
            message=str(err),
            details={"phases": {p.value: [d.value for d in dirs] for p, dirs in phases.items()}},
        ) from err

    # 2. Check if already exists
    repo = JunctionRepository(session)
    existing = await repo.get(req.id)
    if existing is not None:
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="JUNCTION_ALREADY_EXISTS",
            message=f"Junction '{req.id}' already exists.",
            details={"junction_id": req.id},
        )

    # 3. Persist to database
    config_dict = {
        "id": req.id,
        "name": req.name,
        "phases": {p.value: [d.value for d in dirs] for p, dirs in phases.items()},
        "timings": req.timings.model_dump(),
    }
    j_model = await repo.create(junction_id=req.id, name=req.name, config=config_dict)

    # Create initial state row
    initial_state = JunctionStateModel(
        junction_id=req.id,
        version=1,
        mode="AUTOMATIC",
        serving="NS",
        step="BOOT",
        target=None,
        deadline_at=None,
        desired={d.value: "RED" for d in Direction},
        actual={d.value: "UNKNOWN" for d in Direction},
        manual={"active": False},
        emergencies=[],
    )
    await repo.save_state(initial_state)
    await session.commit()

    # 4. Register with manager and start worker
    manager = get_junction_manager()
    worker = manager.register_junction(domain_config)
    await worker.start()

    return JunctionDetail(
        id=j_model.id,
        name=j_model.name,
        config=j_model.config,
        created_at=j_model.created_at,
    )


@router.get("/junctions/{id}", response_model=JunctionDetail)
async def get_junction(
    id: str,
    session: SessionDep,
) -> JunctionDetail:
    worker = await _get_worker_or_404(id)
    repo = JunctionRepository(session)
    j_model = await repo.get(id)
    if j_model is not None:
        return JunctionDetail(
            id=j_model.id,
            name=j_model.name,
            config=j_model.config,
            created_at=j_model.created_at,
        )
    return JunctionDetail(
        id=worker.config.id,
        name=worker.config.name,
        config={
            "phases": {
                p.value: [d.value for d in dirs] for p, dirs in worker.config.phases.items()
            },
            "timings": {
                "green": worker.config.timings.green,
                "yellow": worker.config.timings.yellow,
                "all_red": worker.config.timings.all_red,
                "min_green": worker.config.timings.min_green,
                "max_green": worker.config.timings.max_green,
                "ack_timeout": worker.config.timings.ack_timeout,
                "max_retries": worker.config.timings.max_retries,
            },
        },
        created_at=datetime.now(UTC),
    )


@router.post(
    "/sensor-events",
    response_model=SensorEventResponse,
)
async def ingest_sensor_event(
    req: SensorEventRequest,
    response: Response,
) -> SensorEventResponse:
    worker = await _get_worker_or_404(req.junction_id)

    # Validate event type & vehicle type (D-14)
    if req.event_type == "VEHICLE_ARRIVED":
        if req.vehicle_type is None:
            raise AppError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="INVALID_VEHICLE_TYPE",
                message="Vehicle type is required for VEHICLE_ARRIVED events.",
            )
        event = VehicleArrived(
            event_id=req.event_id,
            junction_id=req.junction_id,
            direction=req.direction,
            vehicle_id=req.vehicle_id,
            vehicle_type=req.vehicle_type,
            sensor_time=req.timestamp.timestamp(),
            server_time=time.time(),
            sequence_no=req.sequence_no,
        )
    elif req.event_type == "VEHICLE_CLEARED":
        event = VehicleCleared(  # type: ignore[assignment]
            event_id=req.event_id,
            junction_id=req.junction_id,
            direction=req.direction,
            vehicle_id=req.vehicle_id,
            sensor_time=req.timestamp.timestamp(),
            server_time=time.time(),
            sequence_no=req.sequence_no,
        )
    else:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_EVENT_TYPE",
            message=f"Unsupported event_type '{req.event_type}'.",
        )

    res = await worker.submit(event)

    # Status mapping per P-02:
    # 201 applied, 200 duplicate, 202 recorded not applied
    if res.get("duplicate"):
        response.status_code = status.HTTP_200_OK
        return SensorEventResponse(
            event_id=res["event_id"],
            status="DUPLICATE",
            duplicate=True,
        )

    if res.get("status") in ("RECORDED_NOT_APPLIED", "NOT_APPLIED"):
        response.status_code = status.HTTP_202_ACCEPTED
        return SensorEventResponse(
            event_id=res["event_id"],
            status="NOT_APPLIED",
            duplicate=False,
            reason=res.get("reason"),
        )

    response.status_code = status.HTTP_201_CREATED
    return SensorEventResponse(
        event_id=res["event_id"],
        status="APPLIED",
        duplicate=False,
    )


@router.get("/junctions/{id}/status", response_model=JunctionStatusResponse)
async def get_junction_status(id: str) -> dict[str, Any]:
    worker = await _get_worker_or_404(id)
    return worker.get_status_dict()


@router.post(
    "/junctions/{id}/commands",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AdminCommandResponse,
)
async def issue_command(id: str, req: AdminCommandRequest) -> AdminCommandResponse:
    worker = await _get_worker_or_404(id)

    if req.command not in ("MANUAL_GREEN_REQUEST", "RETURN_TO_AUTOMATIC"):
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_COMMAND",
            message=f"Unsupported command '{req.command}'.",
        )

    target_phase: Phase | None = None
    if req.command == "MANUAL_GREEN_REQUEST":
        if req.direction is None:
            raise AppError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="MISSING_DIRECTION",
                message="Direction is required for MANUAL_GREEN_REQUEST.",
            )
        target_phase = (
            Phase.NS if req.direction in (Direction.NORTH, Direction.SOUTH) else Phase.EW
        )

    event = AdminCommand(
        junction_id=id,
        command_type=req.command,
        target_phase=target_phase,
        issued_by=req.issued_by,
        server_time=time.time(),
    )
    res = await worker.submit(event)

    # P-04: Manual command in DEGRADED mode returns 409
    if res.get("degraded"):
        raise AppError(
            status_code=status.HTTP_409_CONFLICT,
            code="JUNCTION_DEGRADED",
            message=res.get("message", "Junction is DEGRADED; command rejected."),
        )

    return AdminCommandResponse(
        status="ACCEPTED",
        message="Command accepted and queued",
    )


@router.post("/controller-events", response_model=ControllerEventResponse)
async def ingest_controller_event(req: ControllerEventRequest) -> ControllerEventResponse:
    worker = await _get_worker_or_404(req.junction_id)

    direction = req.direction
    if direction is None:
        tracked_cmd = worker.command_tracker._commands.get(req.command_id)
        direction = tracked_cmd.direction if tracked_cmd is not None else Direction.NORTH

    if req.status == "ACK":
        event = ControllerAck(
            command_id=req.command_id,
            junction_id=req.junction_id,
            direction=direction,
            confirmed_state=req.actual_state or Signal.UNKNOWN,
            server_time=time.time(),
        )
    elif req.status == "NACK":
        event = ControllerNack(  # type: ignore[assignment]
            command_id=req.command_id,
            junction_id=req.junction_id,
            direction=direction,
            reason=req.reason or "Controller NACK",
            server_time=time.time(),
        )
    else:
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_CONTROLLER_STATUS",
            message=f"Unknown controller status '{req.status}'.",
        )

    res = await worker.submit(event)

    if res.get("not_found"):
        raise AppError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="COMMAND_NOT_FOUND",
            message=f"Command '{req.command_id}' not found.",
        )

    return ControllerEventResponse(
        command_id=req.command_id,
        status=res.get("status", "PROCESSED"),
        duplicate=res.get("duplicate", False),
    )


@router.post("/device-status", response_model=DeviceStatusResponse)
async def report_device_status(req: DeviceStatusRequest) -> DeviceStatusResponse:
    worker = await _get_worker_or_404(req.junction_id)

    event = DeviceStatusChanged(
        junction_id=req.junction_id,
        device_type=req.device_type,
        direction=req.direction,
        status=req.status,
        server_time=time.time(),
    )
    res = await worker.submit(event)

    return DeviceStatusResponse(
        event_id=res.get("event_id", req.event_id),
        status=res.get("status", "UPDATED"),
    )


@router.get("/junctions/{id}/history", response_model=list[AuditLogEntry])
async def get_junction_history(
    id: str,
    session: SessionDep,
    limit: int = 50,
    before_id: int | None = None,
    event_type: str | None = None,
) -> list[AuditLogEntry]:
    # Check junction exists
    await _get_worker_or_404(id)

    audit_repo = AuditLogRepository(session)
    entries = await audit_repo.list_by_junction(
        junction_id=id,
        limit=limit,
        before_id=before_id,
        event_type=event_type,
    )
    return [
        AuditLogEntry(
            id=e.id,
            junction_id=e.junction_id,
            event_type=e.event_type,
            direction=e.direction,
            previous_state=e.previous_state,
            new_state=e.new_state,
            command_id=e.command_id,
            reason=e.reason,
            payload=e.payload,
            occurred_at=e.occurred_at,
            source=e.source,
        )
        for e in entries
    ]


@router.get("/junctions/{id}/stream")
async def stream_junction_status(id: str, request: Request) -> StreamingResponse:
    worker = await _get_worker_or_404(id)
    return StreamingResponse(
        sse_event_generator(worker, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/simulator/{id}/mode", response_model=SetSimulatorModeResponse)
async def set_simulator_mode(
    id: str, req: SetSimulatorModeRequest
) -> SetSimulatorModeResponse:
    worker = await _get_worker_or_404(id)

    if req.mode not in ("AUTO_ACK", "DELAYED", "SILENT", "OFFLINE"):
        raise AppError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="INVALID_SIMULATOR_MODE",
            message=f"Unsupported simulator mode '{req.mode}'.",
        )

    if worker.simulator is not None:
        prev_mode = worker.simulator.mode
        worker.simulator.set_mode(SimulatorMode(req.mode))

        # If switching to OFFLINE, signal device status changed
        now = time.time()
        if req.mode == "OFFLINE":
            await worker.submit(
                DeviceStatusChanged(
                    junction_id=id,
                    device_type="SIGNAL_CONTROLLER",
                    direction=None,
                    status="OFFLINE",
                    server_time=now,
                )
            )
        elif prev_mode == SimulatorMode.OFFLINE:
            # Reconnected!
            await worker.submit(
                DeviceStatusChanged(
                    junction_id=id,
                    device_type="SIGNAL_CONTROLLER",
                    direction=None,
                    status="ONLINE",
                    server_time=now,
                )
            )

    return SetSimulatorModeResponse(junction_id=id, mode=req.mode)
