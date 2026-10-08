"""Async database repositories.

Owned by Agent B (Phase 1).
All database interactions flow through these repositories.
AuditLog is strictly append-only (Instruction.md 5.4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    AuditLogModel,
    CommandModel,
    DeviceStatusModel,
    DirectionSequenceModel,
    JunctionModel,
    JunctionStateModel,
    ProcessedEventModel,
    VehicleModel,
)


class JunctionRepository:
    """Repository for junctions and their serialized state snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, junction_id: str, name: str, config: dict[str, Any]) -> JunctionModel:
        junction = JunctionModel(id=junction_id, name=name, config=config)
        self.session.add(junction)
        await self.session.flush()
        return junction

    async def get(self, junction_id: str) -> JunctionModel | None:
        stmt = select(JunctionModel).where(JunctionModel.id == junction_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_all(self) -> list[JunctionModel]:
        stmt = select(JunctionModel).order_by(JunctionModel.id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_state(self, junction_id: str) -> JunctionStateModel | None:
        stmt = select(JunctionStateModel).where(JunctionStateModel.junction_id == junction_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def save_state(self, state_model: JunctionStateModel) -> JunctionStateModel:
        """Upsert junction state."""
        existing = await self.get_state(state_model.junction_id)
        if existing is None:
            self.session.add(state_model)
            await self.session.flush()
            return state_model

        existing.version = state_model.version
        existing.mode = state_model.mode
        existing.serving = state_model.serving
        existing.step = state_model.step
        existing.target = state_model.target
        existing.deadline_at = state_model.deadline_at
        existing.desired = state_model.desired
        existing.actual = state_model.actual
        existing.manual = state_model.manual
        existing.emergencies = state_model.emergencies
        await self.session.flush()
        return existing


class VehicleRepository:
    """Repository managing vehicle queue entries (D-03, P-01)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_waiting(self, junction_id: str) -> list[VehicleModel]:
        stmt = (
            select(VehicleModel)
            .where(VehicleModel.junction_id == junction_id, VehicleModel.status == "WAITING")
            .order_by(VehicleModel.arrived_server_at.asc(), VehicleModel.id.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_waiting_by_vehicle_id(
        self, junction_id: str, vehicle_id: str
    ) -> VehicleModel | None:
        stmt = select(VehicleModel).where(
            VehicleModel.junction_id == junction_id,
            VehicleModel.vehicle_id == vehicle_id,
            VehicleModel.status == "WAITING",
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_last_clear_marker(
        self, junction_id: str, vehicle_id: str, direction: str
    ) -> VehicleModel | None:
        """Find recent CLEARED or ORPHAN_CLEARED marker for orphan-clear ordering check (P-01)."""
        stmt = (
            select(VehicleModel)
            .where(
                VehicleModel.junction_id == junction_id,
                VehicleModel.vehicle_id == vehicle_id,
                VehicleModel.direction == direction,
                VehicleModel.status.in_(["CLEARED", "ORPHAN_CLEARED"]),
            )
            .order_by(VehicleModel.id.desc())
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def record_arrival(
        self,
        junction_id: str,
        vehicle_id: str,
        direction: str,
        vehicle_type: str,
        sequence_no: int,
        sensor_time: datetime | None,
        server_time: float,
    ) -> VehicleModel | None:
        """Add vehicle to WAITING queue if not already waiting."""
        existing = await self.get_waiting_by_vehicle_id(junction_id, vehicle_id)
        if existing is not None:
            return None  # Already waiting, idempotent

        vehicle = VehicleModel(
            junction_id=junction_id,
            vehicle_id=vehicle_id,
            direction=direction,
            vehicle_type=vehicle_type,
            status="WAITING",
            arrival_seq=sequence_no,
            arrived_sensor_at=sensor_time,
            arrived_server_at=server_time,
        )
        self.session.add(vehicle)
        await self.session.flush()
        return vehicle

    async def record_clearance(
        self,
        junction_id: str,
        vehicle_id: str,
        direction: str,
        sequence_no: int,
        server_time: float,
    ) -> tuple[bool, VehicleModel]:
        """Mark waiting vehicle as CLEARED, or record an ORPHAN_CLEARED marker (D-13, P-01).

        Returns (was_waiting, vehicle_model).
        """
        existing = await self.get_waiting_by_vehicle_id(junction_id, vehicle_id)
        if existing is not None:
            existing.status = "CLEARED"
            existing.clear_seq = sequence_no
            existing.cleared_server_at = server_time
            await self.session.flush()
            return True, existing

        # Orphan clearance (D-13, P-01)
        orphan = VehicleModel(
            junction_id=junction_id,
            vehicle_id=vehicle_id,
            direction=direction,
            vehicle_type="UNKNOWN",
            status="ORPHAN_CLEARED",
            clear_seq=sequence_no,
            cleared_server_at=server_time,
        )
        self.session.add(orphan)
        await self.session.flush()
        return False, orphan

    async def get_queue_counts(self, junction_id: str) -> dict[str, int]:
        stmt = (
            select(VehicleModel.direction, func.count(VehicleModel.id))
            .where(VehicleModel.junction_id == junction_id, VehicleModel.status == "WAITING")
            .group_by(VehicleModel.direction)
        )
        res = await self.session.execute(stmt)
        counts = {"NORTH": 0, "SOUTH": 0, "EAST": 0, "WEST": 0}
        for direction, count in res.all():
            counts[direction] = count
        return counts


class ProcessedEventRepository:
    """Repository for deduplication and idempotency records (D-11)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: str) -> ProcessedEventModel | None:
        stmt = select(ProcessedEventModel).where(ProcessedEventModel.event_id == event_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def record(
        self,
        event_id: str,
        junction_id: str,
        outcome: str,
        payload: dict[str, Any],
    ) -> ProcessedEventModel:
        ev = ProcessedEventModel(
            event_id=event_id,
            junction_id=junction_id,
            outcome=outcome,
            payload=payload,
            received_at=datetime.now(UTC),
        )
        self.session.add(ev)
        await self.session.flush()
        return ev


class DirectionSequenceRepository:
    """Tracks sequence numbers per junction direction (D-11, P-01)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_last_sequence(self, junction_id: str, direction: str) -> int:
        stmt = select(DirectionSequenceModel).where(
            DirectionSequenceModel.junction_id == junction_id,
            DirectionSequenceModel.direction == direction,
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        return row.last_sequence_no if row is not None else 0

    async def update_sequence(self, junction_id: str, direction: str, sequence_no: int) -> None:
        stmt = select(DirectionSequenceModel).where(
            DirectionSequenceModel.junction_id == junction_id,
            DirectionSequenceModel.direction == direction,
        )
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        if row is None:
            row = DirectionSequenceModel(
                junction_id=junction_id, direction=direction, last_sequence_no=sequence_no
            )
            self.session.add(row)
        else:
            if sequence_no > row.last_sequence_no:
                row.last_sequence_no = sequence_no
        await self.session.flush()


class CommandRepository:
    """Repository for signal controller commands and their lifecycle (D-19)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_command(
        self,
        command_id: str,
        junction_id: str,
        direction: str,
        requested_state: str,
        sent_at: float,
        deadline_at: float,
        status: str = "PENDING",
    ) -> CommandModel:
        existing = await self.get(command_id)
        if existing is not None:
            existing.attempts += 1
            existing.deadline_at = deadline_at
            await self.session.flush()
            return existing

        cmd = CommandModel(
            command_id=command_id,
            junction_id=junction_id,
            direction=direction,
            requested_state=requested_state,
            status=status,
            attempts=1,
            sent_at=sent_at,
            deadline_at=deadline_at,
        )
        self.session.add(cmd)
        await self.session.flush()
        return cmd

    async def get(self, command_id: str) -> CommandModel | None:
        stmt = select(CommandModel).where(CommandModel.command_id == command_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_pending(self, junction_id: str) -> list[CommandModel]:
        stmt = select(CommandModel).where(
            CommandModel.junction_id == junction_id, CommandModel.status == "PENDING"
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def record_ack(
        self, command_id: str, acked_at: float, actual_state: str
    ) -> CommandModel | None:
        cmd = await self.get(command_id)
        if cmd is not None:
            cmd.status = "ACKED"
            cmd.acked_at = acked_at
            cmd.actual_state = actual_state
            await self.session.flush()
        return cmd

    async def record_retry(self, command_id: str, deadline_at: float) -> CommandModel | None:
        cmd = await self.get(command_id)
        if cmd is not None:
            cmd.attempts += 1
            cmd.deadline_at = deadline_at
            await self.session.flush()
        return cmd

    async def record_failed(self, command_id: str) -> CommandModel | None:
        """Mark command as FAILED upon timeout exceeding max retries or controller NACK (D-19)."""
        cmd = await self.get(command_id)
        if cmd is not None:
            cmd.status = "FAILED"
            await self.session.flush()
        return cmd

    async def abandon_pending(self, junction_id: str) -> int:
        """Mark all pending commands as ABANDONED on boot recovery (D-20)."""
        stmt = (
            update(CommandModel)
            .where(CommandModel.junction_id == junction_id, CommandModel.status == "PENDING")
            .values(status="ABANDONED")
        )
        res = await self.session.execute(stmt)
        rowcount = getattr(res, "rowcount", 0)
        return int(rowcount) if rowcount is not None else 0


class DeviceStatusRepository:
    """Repository for device statuses (controllers and sensors)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def update_status(
        self, junction_id: str, device_type: str, direction: str, status: str
    ) -> DeviceStatusModel:
        stmt = select(DeviceStatusModel).where(
            DeviceStatusModel.junction_id == junction_id,
            DeviceStatusModel.device_type == device_type,
            DeviceStatusModel.direction == direction,
        )
        res = await self.session.execute(stmt)
        dev = res.scalar_one_or_none()
        if dev is None:
            dev = DeviceStatusModel(
                junction_id=junction_id,
                device_type=device_type,
                direction=direction,
                status=status,
            )
            self.session.add(dev)
        else:
            dev.status = status
            dev.updated_at = datetime.now(UTC)
        await self.session.flush()
        return dev

    async def get_for_junction(self, junction_id: str) -> list[DeviceStatusModel]:
        stmt = select(DeviceStatusModel).where(DeviceStatusModel.junction_id == junction_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


class AuditLogRepository:
    """Strictly append-only audit log repository (Instruction.md 5.4, Rule 198).

    No UPDATE or DELETE methods exist in this class.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        junction_id: str,
        event_type: str,
        direction: str | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        command_id: str | None = None,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "SYSTEM",
    ) -> AuditLogModel:
        """Append an audit entry (append-only)."""
        entry = AuditLogModel(
            junction_id=junction_id,
            event_type=event_type,
            direction=direction,
            previous_state=previous_state,
            new_state=new_state,
            command_id=command_id,
            reason=reason,
            payload=payload,
            occurred_at=datetime.now(UTC),
            source=source,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_by_junction(
        self,
        junction_id: str,
        limit: int = 50,
        before_id: int | None = None,
        event_type: str | None = None,
    ) -> list[AuditLogModel]:
        stmt = select(AuditLogModel).where(AuditLogModel.junction_id == junction_id)
        if before_id is not None:
            stmt = stmt.where(AuditLogModel.id < before_id)
        if event_type is not None:
            stmt = stmt.where(AuditLogModel.event_type == event_type)
        stmt = stmt.order_by(AuditLogModel.id.desc()).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
