"""Executes engine-produced domain effects after database commit.

Owned by Agent C (Phase 1).
"""

from __future__ import annotations

import logging

from app.domain.effects import Alert, DomainEffect, RecordAudit, SendSignalCommand
from app.domain.ports import ControllerPort

logger = logging.getLogger("factory_traffic.effects")


class EffectExecutor:
    """Executes effects returned by the domain engine after DB transaction commits."""

    def __init__(self, controller: ControllerPort) -> None:
        self.controller = controller

    async def execute_effects(self, effects: list[DomainEffect]) -> None:
        for eff in effects:
            if isinstance(eff, SendSignalCommand):
                await self.controller.send(eff)
            elif isinstance(eff, Alert):
                logger.warning(
                    "ALERT: %s - %s (details: %s)",
                    eff.alert_type,
                    eff.message,
                    eff.details,
                )
            elif isinstance(eff, RecordAudit):
                logger.debug(
                    "AUDIT: %s (direction: %s, reason: %s)",
                    eff.event_type,
                    eff.direction,
                    eff.reason,
                )
