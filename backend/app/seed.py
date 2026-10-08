"""Database seed script for Factory Traffic Management System.

Seeds initial Junction A configuration per Instruction.md sections 6 and 10.
Owned by Agent B (Phase 1); scaffolded by Agent 0 (Phase 0).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.domain.types import Direction, Phase, TimingsConfig, VehicleType
from app.infrastructure.db.models import JunctionModel, JunctionStateModel
from app.infrastructure.db.session import async_session_factory

logger = logging.getLogger("factory_traffic.seed")

_default_timings = TimingsConfig()

JUNCTION_A_CONFIG: dict[str, Any] = {
    "id": "A",
    "name": "Junction A",
    "phases": {
        Phase.NS.value: [Direction.NORTH.value, Direction.SOUTH.value],
        Phase.EW.value: [Direction.EAST.value, Direction.WEST.value],
    },
    "timings": {
        "green": _default_timings.green,
        "yellow": _default_timings.yellow,
        "all_red": _default_timings.all_red,
        "min_green": _default_timings.min_green,
        "max_green": _default_timings.max_green,
        "ack_timeout": _default_timings.ack_timeout,
        "max_retries": _default_timings.max_retries,
        "starvation_after": _default_timings.starvation_after,
        "emergency_timeout": _default_timings.emergency_timeout,
        "manual_lease": _default_timings.manual_lease,
        "stale_event_after": _default_timings.stale_event_after,
    },
    "vehicle_weights": {
        VehicleType.TRUCK.value: 3,
        VehicleType.FORKLIFT.value: 2,
        VehicleType.EMPLOYEE_VEHICLE.value: 1,
        VehicleType.EMERGENCY.value: 0,
    },
}


async def seed_junction_a() -> None:
    """Insert default Junction A if not present."""
    logging.basicConfig(level=logging.INFO)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = select(JunctionModel).where(JunctionModel.id == "A")
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()
                if existing is not None:
                    logger.info("Junction A already exists in database.")
                    return

                junction = JunctionModel(
                    id="A",
                    name="Junction A",
                    config=JUNCTION_A_CONFIG,
                )
                session.add(junction)

                initial_state = JunctionStateModel(
                    junction_id="A",
                    version=1,
                    mode="AUTOMATIC",
                    serving="NS",
                    step="BOOT",
                    target=None,
                    deadline_at=None,
                    desired={
                        Direction.NORTH.value: "RED",
                        Direction.SOUTH.value: "RED",
                        Direction.EAST.value: "RED",
                        Direction.WEST.value: "RED",
                    },
                    actual={
                        Direction.NORTH.value: "UNKNOWN",
                        Direction.SOUTH.value: "UNKNOWN",
                        Direction.EAST.value: "UNKNOWN",
                        Direction.WEST.value: "UNKNOWN",
                    },
                    manual={"active": False},
                    emergencies=[],
                )
                session.add(initial_state)
            logger.info("Successfully seeded Junction A into database.")
    except Exception as exc:
        logger.warning(
            "Could not connect to database to seed Junction A (%s). "
            "Ensure PostgreSQL is running and migrations have been applied.",
            exc,
        )


if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed_junction_a())
