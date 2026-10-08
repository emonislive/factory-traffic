"""SQLAlchemy 2.0 Declarative Models matching contracts/schema.sql.

Owned by Agent B (Phase 1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONB_COMPAT = JSON().with_variant(postgresql.JSONB(), "postgresql")
BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass



class JunctionModel(Base):
    __tablename__ = "junctions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB_COMPAT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JunctionStateModel(Base):
    __tablename__ = "junction_state"

    junction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("junctions.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    serving: Mapped[str] = mapped_column(String(16), nullable=False)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deadline_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    desired: Mapped[dict[str, Any]] = mapped_column(JSONB_COMPAT, nullable=False)
    actual: Mapped[dict[str, Any]] = mapped_column(JSONB_COMPAT, nullable=False)
    manual: Mapped[dict[str, Any]] = mapped_column(JSONB_COMPAT, nullable=False)
    emergencies: Mapped[list[Any]] = mapped_column(JSONB_COMPAT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class VehicleModel(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    junction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("junctions.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # WAITING, CLEARED, ORPHAN_CLEARED
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    arrival_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    clear_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    arrived_server_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrived_sensor_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cleared_server_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index(
            "idx_vehicles_unique_waiting",
            "junction_id",
            "vehicle_id",
            unique=True,
            postgresql_where=(status == "WAITING"),
        ),
        Index("idx_vehicles_junction_direction_status", "junction_id", "direction", "status"),
    )


class ProcessedEventModel(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    junction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("junctions.id", ondelete="CASCADE"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB_COMPAT, nullable=False)


class DirectionSequenceModel(Base):
    __tablename__ = "direction_sequence"

    junction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("junctions.id", ondelete="CASCADE"), primary_key=True
    )
    direction: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_sequence_no: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class CommandModel(Base):
    __tablename__ = "commands"

    command_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    junction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("junctions.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_state: Mapped[str] = mapped_column(String(16), nullable=False)
    # PENDING, ACKED, FAILED, ABANDONED
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sent_at: Mapped[float] = mapped_column(Float, nullable=False)
    deadline_at: Mapped[float] = mapped_column(Float, nullable=False)
    acked_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_state: Mapped[str | None] = mapped_column(String(16), nullable=True)


class DeviceStatusModel(Base):
    __tablename__ = "device_status"

    junction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("junctions.id", ondelete="CASCADE"), primary_key=True
    )
    device_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    direction: Mapped[str] = mapped_column(String(16), primary_key=True, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    junction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("junctions.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    command_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB_COMPAT, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[str] = mapped_column(String(64), default="SYSTEM", nullable=False)

    __table_args__ = (
        Index("idx_audit_log_junction_occurred", "junction_id", id.desc()),
    )
