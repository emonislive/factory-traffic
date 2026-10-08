"""Serialized per-junction worker queue and loop (D-01).

Implements single-writer event loop, transactional persistence,
effect execution, and live SSE status broadcasting.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.command_tracker import CommandTracker
from app.application.effect_executor import EffectExecutor
from app.application.ticker import Ticker
from app.domain.effects import DomainEffect, RecordAudit, SendSignalCommand
from app.domain.engine import process_event
from app.domain.events import (
    AdminCommand,
    ControllerAck,
    ControllerNack,
    DeviceStatusChanged,
    Tick,
    VehicleArrived,
    VehicleCleared,
)
from app.domain.ports import ControllerPort
from app.domain.types import (
    Direction,
    JunctionConfig,
    JunctionState,
    ManualState,
    Mode,
    Phase,
    Signal,
    Step,
)
from app.infrastructure.controllers.rest_simulator import (
    RestSimulatorController,
    SimulatorMode,
)
from app.infrastructure.db.models import JunctionStateModel
from app.infrastructure.db.repositories import (
    AuditLogRepository,
    CommandRepository,
    DeviceStatusRepository,
    DirectionSequenceRepository,
    JunctionRepository,
    ProcessedEventRepository,
    VehicleRepository,
)
from app.infrastructure.db.session import async_session_factory

logger = logging.getLogger("factory_traffic.worker")


class JunctionWorker:
    """Manages an in-memory queue and background processing loop for a single junction (D-01)."""

    def __init__(
        self,
        junction_id: str,
        config: JunctionConfig,
        session_factory: async_sessionmaker[AsyncSession],
        controller: ControllerPort | None = None,
    ) -> None:
        self.junction_id = junction_id
        self.config = config
        self.session_factory = session_factory

        # Controller adapter (REST simulator by default)
        if controller is None:
            sim = RestSimulatorController(junction_id=junction_id, mode=SimulatorMode.AUTO_ACK)
            self.simulator: RestSimulatorController | None = sim
            self.controller: ControllerPort = sim
        else:
            self.controller = controller
            self.simulator = (
                controller if isinstance(controller, RestSimulatorController) else None
            )

        self.command_tracker = CommandTracker(
            ack_timeout=config.timings.ack_timeout,
            max_retries=config.timings.max_retries,
        )
        self.effect_executor = EffectExecutor(self.controller)
        self.ticker = Ticker(interval_seconds=0.5, on_tick=self._on_ticker_tick)

        # Wire simulator callback to worker queue
        if self.simulator is not None:
            self.simulator.set_ack_handler(self.submit)

        self.queue: asyncio.Queue[tuple[Any, asyncio.Future[Any]]] = asyncio.Queue()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._running = False
        self._worker_task: asyncio.Task[None] | None = None
        self.sensor_statuses: dict[Direction, str] = {}

        # Initial state (safe default)
        self.state = JunctionState(
            version=1,
            mode=Mode.AUTOMATIC,
            serving=Phase.NS,
            step=Step.BOOT,
            target=None,
            deadline_at=None,
            desired={
                Direction.NORTH: Signal.RED,
                Direction.SOUTH: Signal.RED,
                Direction.EAST: Signal.RED,
                Direction.WEST: Signal.RED,
            },
            actual={
                Direction.NORTH: Signal.UNKNOWN,
                Direction.SOUTH: Signal.UNKNOWN,
                Direction.EAST: Signal.UNKNOWN,
                Direction.WEST: Signal.UNKNOWN,
            },
            pending_command_ids=[],
            manual=ManualState(active=False),
            emergencies=[],
            waiting_vehicles=[],
            alerts=[],
        )

    async def start(self) -> None:
        """Start worker consumer task and periodic ticker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._run_loop())
        await self.ticker.start()
        logger.info("Worker started for junction %s", self.junction_id)

    async def stop(self) -> None:
        """Stop worker task and periodic ticker."""
        self._running = False
        await self.ticker.stop()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None
        logger.info("Worker stopped for junction %s", self.junction_id)

    async def submit(self, event: Any) -> Any:
        """Submit an event to the junction queue and await processing result (D-01)."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        await self.queue.put((event, future))
        return await future

    async def _on_ticker_tick(self) -> None:
        """Invoked periodically every 500ms by the Ticker."""
        if not self._running:
            return
        tick = Tick(junction_id=self.junction_id, server_time=time.time())
        await self.submit(tick)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to live state broadcasts (SSE)."""
        sub_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(sub_queue)
        return sub_queue

    def unsubscribe(self, sub_queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe from live state broadcasts."""
        self._subscribers.discard(sub_queue)

    def _broadcast_status(self) -> None:
        """Push latest status snapshot to all active SSE subscribers."""
        if not self._subscribers:
            return
        status_payload = self.get_status_dict()
        dead_subs = set()
        for sub in self._subscribers:
            try:
                sub.put_nowait(status_payload)
            except asyncio.QueueFull:
                dead_subs.add(sub)
            except Exception:
                dead_subs.add(sub)
        self._subscribers.difference_update(dead_subs)

    def get_status_dict(self) -> dict[str, Any]:
        """Generate status snapshot matching openapi.yaml JunctionStatusResponse."""
        counts = {"NORTH": 0, "SOUTH": 0, "EAST": 0, "WEST": 0}
        for v in self.state.waiting_vehicles:
            counts[v.direction.value] += 1

        active_em = bool(self.state.emergencies)
        em_dir = self.state.emergencies[0].direction.value if active_em else None
        em_veh = self.state.emergencies[0].vehicle_id if active_em else None

        controller_status = "OFFLINE" if "CONTROLLER_OFFLINE" in self.state.alerts else "ONLINE"
        if self.state.mode == Mode.DEGRADED and controller_status != "OFFLINE":
            controller_status = "DEGRADED"

        stale_queues = [
            d.value for d, st in self.sensor_statuses.items() if st == "OFFLINE"
        ]
        device_statuses: dict[str, Any] = {
            "SIGNAL_CONTROLLER": {"status": controller_status}
        }
        for d, st in self.sensor_statuses.items():
            device_statuses[f"SENSOR_{d.value}"] = {"status": st}

        return {
            "junction_id": self.junction_id,
            "mode": self.state.mode.value,
            "phase": self.state.serving.value,
            "controller_status": controller_status,
            "desired_signals": {d.value: sig.value for d, sig in self.state.desired.items()},
            "actual_signals": {d.value: sig.value for d, sig in self.state.actual.items()},
            "queues": counts,
            "transition": {
                "step": self.state.step.value,
                "target": self.state.target.value if self.state.target else None,
                "deadline_at": self.state.deadline_at,
            },
            "pending_commands": list(self.state.pending_command_ids),
            "emergency": {
                "active": active_em,
                "direction": em_dir,
                "vehicle_id": em_veh,
            },
            "manual": {
                "active": self.state.manual.active,
                "lease_expires_at": self.state.manual.lease_expires_at,
                "issued_by": self.state.manual.issued_by,
            },
            "alerts": list(self.state.alerts),
            "device_statuses": device_statuses,
            "stale_queues": stale_queues,
        }

    async def _run_loop(self) -> None:
        """Main serialized worker loop consuming from the junction queue."""
        while self._running:
            try:
                event, future = await self.queue.get()
                try:
                    result = await self._process_one_event(event)
                    if not future.done():
                        future.set_result(result)
                except Exception as exc:
                    logger.exception("Error processing event in worker %s", self.junction_id)
                    if not future.done():
                        future.set_exception(exc)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as loop_exc:
                logger.error("Fatal error in worker loop %s: %s", self.junction_id, loop_exc)

    async def _process_one_event(self, event: Any) -> Any:
        now = time.time()

        # 1. Pre-processing & Deduplication
        async with self.session_factory() as session:
            processed_repo = ProcessedEventRepository(session)
            vehicle_repo = VehicleRepository(session)

            if isinstance(event, (VehicleArrived, VehicleCleared)):
                # Deduplication by event_id (D-11, P-02)
                existing_ev = await processed_repo.get(event.event_id)
                if existing_ev is not None:
                    return {
                        "event_id": event.event_id,
                        "status": "DUPLICATE",
                        "duplicate": True,
                    }

                # Stale event check (D-12, P-02)
                stale_limit = self.config.timings.stale_event_after
                if abs(event.server_time - event.sensor_time) > stale_limit:
                    async with session.begin():
                        await processed_repo.record(
                            event.event_id,
                            self.junction_id,
                            "STALE",
                            {"reason": "Sensor event timestamp stale (> 5m)"},
                        )
                    return {
                        "event_id": event.event_id,
                        "status": "RECORDED_NOT_APPLIED",
                        "duplicate": False,
                        "reason": "Sensor event timestamp stale (> 5m)",
                    }

                # Orphan-clear ordering rule (P-01)
                if isinstance(event, VehicleArrived):
                    last_clear = await vehicle_repo.get_last_clear_marker(
                        self.junction_id, event.vehicle_id, event.direction.value
                    )
                    if last_clear is not None and last_clear.clear_seq is not None:
                        if event.sequence_no <= last_clear.clear_seq:
                            async with session.begin():
                                await processed_repo.record(
                                    event.event_id,
                                    self.junction_id,
                                    "ORPHAN_CLEAR_PRECEDED",
                                    {"clear_seq": last_clear.clear_seq},
                                )
                            return {
                                "event_id": event.event_id,
                                "status": "RECORDED_NOT_APPLIED",
                                "duplicate": False,
                                "reason": "Arrival preceded by clearance marker",
                            }

            elif isinstance(event, ControllerAck):
                # Duplicate/late/unknown ACK check (D-19, P-02)
                is_valid, reason = self.command_tracker.record_ack(event.command_id, now)
                if reason == "UNKNOWN":
                    return {
                        "command_id": event.command_id,
                        "status": "UNKNOWN",
                        "duplicate": False,
                        "not_found": True,
                    }
                if reason in ("DUPLICATE", "LATE"):
                    return {
                        "command_id": event.command_id,
                        "status": reason,
                        "duplicate": True,
                    }

            elif isinstance(event, ControllerNack):
                # Unknown NACK check (D-19, P-02)
                cmd = self.command_tracker._commands.get(event.command_id)
                if cmd is None:
                    cmd_repo = CommandRepository(session)
                    db_cmd = await cmd_repo.get(event.command_id)
                    if db_cmd is None:
                        return {
                            "command_id": event.command_id,
                            "status": "UNKNOWN",
                            "duplicate": False,
                            "not_found": True,
                        }
                self.command_tracker.mark_failed(event.command_id)

            elif isinstance(event, AdminCommand):
                # P-04: Manual command in DEGRADED mode rejected with 409
                if (
                    self.state.mode == Mode.DEGRADED
                    and event.command_type == "MANUAL_GREEN_REQUEST"
                ):
                    return {
                        "status": "REJECTED",
                        "message": "Junction is in DEGRADED mode; manual command rejected per P-04",
                        "degraded": True,
                    }

        # 2. Check timeouts during Tick
        timeout_effects: list[DomainEffect] = []
        failed_cmd_ids: list[str] = []
        if isinstance(event, Tick):
            timed_out = self.command_tracker.check_timeouts(now)
            for cmd, can_retry in timed_out:
                if can_retry:
                    self.command_tracker.record_retry(cmd.command_id, now)
                    logger.warning(
                        "Command %s timed out, retrying attempt %d (D-19)",
                        cmd.command_id,
                        cmd.attempts + 1,
                    )
                    timeout_effects.append(
                        SendSignalCommand(cmd.command_id, cmd.direction, cmd.requested_state)
                    )
                else:
                    self.command_tracker.mark_failed(cmd.command_id)
                    failed_cmd_ids.append(cmd.command_id)
                    logger.error(
                        "Command %s exceeded retry limit, controller failing (D-19)",
                        cmd.command_id,
                    )
                    nack = ControllerNack(
                        command_id=cmd.command_id,
                        junction_id=self.junction_id,
                        direction=cmd.direction,
                        reason="ACK_TIMEOUT",
                        server_time=now,
                    )
                    nack_state, nack_eff = process_event(self.state, self.config, nack, now)
                    self.state = nack_state
                    timeout_effects.extend(nack_eff)

        # 3. Process event through pure domain engine (D-02)
        new_state, engine_effects = process_event(self.state, self.config, event, now)
        all_effects = timeout_effects + engine_effects

        # 4. Single DB Transaction Write-Path (Instruction.md 5.4)
        was_waiting: bool = True
        async with self.session_factory() as session:
            async with session.begin():
                junction_repo = JunctionRepository(session)
                vehicle_repo = VehicleRepository(session)
                processed_repo = ProcessedEventRepository(session)
                seq_repo = DirectionSequenceRepository(session)
                command_repo = CommandRepository(session)
                audit_repo = AuditLogRepository(session)
                device_repo = DeviceStatusRepository(session)

                # Persist junction state
                state_model = JunctionStateModel(
                    junction_id=self.junction_id,
                    version=new_state.version,
                    mode=new_state.mode.value,
                    serving=new_state.serving.value,
                    step=new_state.step.value,
                    target=new_state.target.value if new_state.target else None,
                    deadline_at=new_state.deadline_at,
                    desired={d.value: sig.value for d, sig in new_state.desired.items()},
                    actual={d.value: sig.value for d, sig in new_state.actual.items()},
                    manual={
                        "active": new_state.manual.active,
                        "lease_expires_at": new_state.manual.lease_expires_at,
                        "target_phase": (
                            new_state.manual.target_phase.value
                            if new_state.manual.target_phase
                            else None
                        ),
                        "issued_by": new_state.manual.issued_by,
                    },
                    emergencies=[
                        {
                            "vehicle_id": e.vehicle_id,
                            "direction": e.direction.value,
                            "phase": e.phase.value,
                            "detected_at": e.detected_at,
                            "expires_at": e.expires_at,
                        }
                        for e in new_state.emergencies
                    ],
                )
                await junction_repo.save_state(state_model)

                # Persist vehicle events
                if isinstance(event, VehicleArrived):
                    await vehicle_repo.record_arrival(
                        junction_id=self.junction_id,
                        vehicle_id=event.vehicle_id,
                        direction=event.direction.value,
                        vehicle_type=event.vehicle_type.value,
                        sequence_no=event.sequence_no,
                        sensor_time=datetime.fromtimestamp(event.sensor_time, UTC),
                        server_time=event.server_time,
                    )
                    await seq_repo.update_sequence(
                        self.junction_id, event.direction.value, event.sequence_no
                    )
                    await processed_repo.record(
                        event.event_id,
                        self.junction_id,
                        "APPLIED",
                        {"vehicle_id": event.vehicle_id, "type": event.vehicle_type.value},
                    )

                elif isinstance(event, VehicleCleared):
                    was_waiting, _ = await vehicle_repo.record_clearance(
                        junction_id=self.junction_id,
                        vehicle_id=event.vehicle_id,
                        direction=event.direction.value,
                        sequence_no=event.sequence_no,
                        server_time=event.server_time,
                    )
                    await seq_repo.update_sequence(
                        self.junction_id, event.direction.value, event.sequence_no
                    )
                    outcome = "APPLIED" if was_waiting else "ORPHAN_CLEARED"
                    await processed_repo.record(
                        event.event_id,
                        self.junction_id,
                        outcome,
                        {"vehicle_id": event.vehicle_id},
                    )

                elif isinstance(event, ControllerAck):
                    await command_repo.record_ack(
                        event.command_id, event.server_time, event.confirmed_state.value
                    )

                elif isinstance(event, ControllerNack):
                    await command_repo.record_failed(event.command_id)

                elif isinstance(event, DeviceStatusChanged):
                    if event.device_type == "SENSOR" and event.direction:
                        self.sensor_statuses[event.direction] = event.status
                    await device_repo.update_status(
                        self.junction_id,
                        event.device_type,
                        event.direction.value if event.direction else "",
                        event.status,
                    )

                for cid in failed_cmd_ids:
                    await command_repo.record_failed(cid)

                # Record emitted commands in DB
                for eff in all_effects:
                    if isinstance(eff, SendSignalCommand):
                        self.command_tracker.record_command_sent(eff, self.junction_id, now)
                        await command_repo.record_command(
                            command_id=eff.command_id,
                            junction_id=self.junction_id,
                            direction=eff.direction.value,
                            requested_state=eff.requested_state.value,
                            sent_at=now,
                            deadline_at=now + self.config.timings.ack_timeout,
                            status="PENDING",
                        )
                    elif isinstance(eff, RecordAudit):
                        await audit_repo.append(
                            junction_id=self.junction_id,
                            event_type=eff.event_type,
                            direction=eff.direction.value if eff.direction else None,
                            previous_state=eff.previous_state.value if eff.previous_state else None,
                            new_state=eff.new_state.value if eff.new_state else None,
                            command_id=eff.command_id,
                            reason=eff.reason,
                            payload=eff.payload,
                        )

        # 5. Commit succeeded: update in-memory state and execute physical effects
        self.state = new_state
        await self.effect_executor.execute_effects(all_effects)
        self._broadcast_status()

        # 6. Format response
        if isinstance(event, VehicleArrived):
            return {
                "event_id": event.event_id,
                "status": "APPLIED",
                "duplicate": False,
            }
        if isinstance(event, VehicleCleared):
            if not was_waiting:
                return {
                    "event_id": event.event_id,
                    "status": "RECORDED_NOT_APPLIED",
                    "duplicate": False,
                    "reason": "Orphan clearance marker recorded (no waiting vehicle)",
                }
            return {
                "event_id": event.event_id,
                "status": "APPLIED",
                "duplicate": False,
            }
        if isinstance(event, ControllerAck):
            return {
                "command_id": event.command_id,
                "status": "PROCESSED",
                "duplicate": False,
            }
        if isinstance(event, ControllerNack):
            return {
                "command_id": event.command_id,
                "status": "PROCESSED",
                "duplicate": False,
            }
        if isinstance(event, AdminCommand):
            return {
                "status": "ACCEPTED",
                "message": "Command queued and applied",
            }
        if isinstance(event, DeviceStatusChanged):
            return {
                "event_id": f"status-{int(now)}",
                "status": "UPDATED",
            }
        return {"status": "OK"}


class JunctionManager:
    """Manages all JunctionWorker instances and application lifecycle."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._workers: dict[str, JunctionWorker] = {}

    def register_junction(
        self,
        config: JunctionConfig,
        controller: ControllerPort | None = None,
    ) -> JunctionWorker:
        """Register or retrieve an existing JunctionWorker."""
        if config.id in self._workers:
            return self._workers[config.id]
        worker = JunctionWorker(
            junction_id=config.id,
            config=config,
            session_factory=self.session_factory,
            controller=controller,
        )
        self._workers[config.id] = worker
        return worker

    def get_worker(self, junction_id: str) -> JunctionWorker | None:
        return self._workers.get(junction_id)

    def list_workers(self) -> list[JunctionWorker]:
        return list(self._workers.values())

    async def start_all(self) -> None:
        """Start all workers and execute boot recovery for registered junctions."""
        from app.application.recovery import recover_junction

        for j_id, worker in self._workers.items():
            await worker.start()
            await recover_junction(j_id, worker, self.session_factory)
        logger.info("All junction workers started and recovered (%d)", len(self._workers))

    async def stop_all(self) -> None:
        """Stop all workers."""
        for worker in self._workers.values():
            await worker.stop()
        logger.info("All junction workers stopped")


default_junction_manager = JunctionManager(session_factory=async_session_factory)


def get_junction_manager() -> JunctionManager:
    return default_junction_manager

