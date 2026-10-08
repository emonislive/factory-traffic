"""Application boot recovery sequence (D-20).

On boot: load saved state, set actual states to UNKNOWN, mark pending commands
ABANDONED, request ALL_RED, and await confirmation before entering AUTOMATIC.
Re-derives emergencies from WAITING EMERGENCY vehicles in persistence.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.events import Boot
from app.domain.types import (
    Direction,
    ManualState,
    Mode,
    Phase,
    VehicleType,
    WaitingVehicle,
)
from app.infrastructure.db.repositories import (
    CommandRepository,
    JunctionRepository,
    VehicleRepository,
)

if TYPE_CHECKING:
    from app.application.junction_worker import JunctionWorker

logger = logging.getLogger("factory_traffic.recovery")


async def recover_junction(
    junction_id: str,
    worker: JunctionWorker,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Execute startup recovery for a junction per D-20."""
    logger.info("Starting boot recovery for junction %s (D-20)", junction_id)
    now = time.time()

    async with session_factory() as session:
        async with session.begin():
            junction_repo = JunctionRepository(session)
            command_repo = CommandRepository(session)
            vehicle_repo = VehicleRepository(session)

            # 1. Mark all pending commands as ABANDONED (INV-8, D-20)
            abandoned_count = await command_repo.abandon_pending(junction_id)
            worker.command_tracker.abandon_all()
            logger.info("Marked %d pending commands as ABANDONED", abandoned_count)

            # 2. Check saved state
            state_model = await junction_repo.get_state(junction_id)
            if state_model is not None:
                logger.info(
                    "Loaded saved state for junction %s: mode=%s, step=%s",
                    junction_id,
                    state_model.mode,
                    state_model.step,
                )
                worker.state.version = state_model.version
                try:
                    worker.state.serving = Phase(state_model.serving)
                except Exception:
                    worker.state.serving = Phase.NS
                try:
                    worker.state.mode = Mode(state_model.mode)
                except Exception:
                    worker.state.mode = Mode.AUTOMATIC
                if state_model.manual:
                    target_phase_str = state_model.manual.get("target_phase")
                    worker.state.manual = ManualState(
                        active=bool(state_model.manual.get("active", False)),
                        lease_expires_at=state_model.manual.get("lease_expires_at"),
                        target_phase=Phase(target_phase_str) if target_phase_str else None,
                        issued_by=state_model.manual.get("issued_by"),
                    )

            # 3. Re-derive waiting vehicles from persistence (D-20, D-03)
            waiting = await vehicle_repo.get_waiting(junction_id)
            logger.info("Loaded %d waiting vehicles from database", len(waiting))
            worker.state.waiting_vehicles = [
                WaitingVehicle(
                    vehicle_id=row.vehicle_id,
                    direction=Direction(row.direction),
                    vehicle_type=VehicleType(row.vehicle_type),
                    arrived_at=row.arrived_server_at or now,
                    sequence_no=row.arrival_seq or 0,
                )
                for row in waiting
                if row.vehicle_type in VehicleType._value2member_map_
            ]

    # 4. Submit Boot event to the junction worker queue to re-derive emergencies and request ALL_RED
    boot_event = Boot(junction_id=junction_id, server_time=now)
    await worker.submit(boot_event)
    logger.info("Boot event submitted and processed for junction %s", junction_id)
