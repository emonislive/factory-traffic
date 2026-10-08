"""Initial schema for factory traffic management system.

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-10-08 12:00:00.000000

Matches contracts/schema.sql and models.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "junctions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("config", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "junction_state",
        sa.Column(
            "junction_id",
            sa.String(length=64),
            sa.ForeignKey("junctions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("serving", sa.String(length=16), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=16), nullable=True),
        sa.Column("deadline_at", sa.Float(), nullable=True),
        sa.Column("desired", json_type, nullable=False),
        sa.Column("actual", json_type, nullable=False),
        sa.Column("manual", json_type, nullable=False),
        sa.Column("emergencies", json_type, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "vehicles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "junction_id",
            sa.String(length=64),
            sa.ForeignKey("junctions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vehicle_id", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("vehicle_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("arrival_seq", sa.BigInteger(), nullable=True),
        sa.Column("clear_seq", sa.BigInteger(), nullable=True),
        sa.Column("arrived_server_at", sa.Float(), nullable=True),
        sa.Column("arrived_sensor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_server_at", sa.Float(), nullable=True),
    )
    op.create_index(
        "idx_vehicles_unique_waiting",
        "vehicles",
        ["junction_id", "vehicle_id"],
        unique=True,
        postgresql_where=sa.text("status = 'WAITING'"),
    )
    op.create_index(
        "idx_vehicles_junction_direction_status",
        "vehicles",
        ["junction_id", "direction", "status"],
    )

    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "junction_id",
            sa.String(length=64),
            sa.ForeignKey("junctions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("payload", json_type, nullable=False),
    )

    op.create_table(
        "direction_sequence",
        sa.Column(
            "junction_id",
            sa.String(length=64),
            sa.ForeignKey("junctions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("direction", sa.String(length=16), primary_key=True),
        sa.Column("last_sequence_no", sa.BigInteger(), nullable=False, server_default="0"),
    )

    op.create_table(
        "commands",
        sa.Column("command_id", sa.String(length=128), primary_key=True),
        sa.Column(
            "junction_id",
            sa.String(length=64),
            sa.ForeignKey("junctions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("requested_state", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sent_at", sa.Float(), nullable=False),
        sa.Column("deadline_at", sa.Float(), nullable=False),
        sa.Column("acked_at", sa.Float(), nullable=True),
        sa.Column("actual_state", sa.String(length=16), nullable=True),
    )

    op.create_table(
        "device_status",
        sa.Column(
            "junction_id",
            sa.String(length=64),
            sa.ForeignKey("junctions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("device_type", sa.String(length=64), primary_key=True),
        sa.Column("direction", sa.String(length=16), primary_key=True, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "junction_id",
            sa.String(length=64),
            sa.ForeignKey("junctions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("previous_state", sa.String(length=16), nullable=True),
        sa.Column("new_state", sa.String(length=16), nullable=True),
        sa.Column("command_id", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", json_type, nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="SYSTEM"),
    )
    op.create_index(
        "idx_audit_log_junction_occurred",
        "audit_log",
        ["junction_id", sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("device_status")
    op.drop_table("commands")
    op.drop_table("direction_sequence")
    op.drop_table("processed_events")
    op.drop_table("vehicles")
    op.drop_table("junction_state")
    op.drop_table("junctions")
