"""REST simulator adapter implementing ControllerPort (D-04).

Supports modes: AUTO_ACK, DELAYED, SILENT, OFFLINE.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations

from enum import StrEnum

from app.domain.effects import SendSignalCommand
from app.domain.ports import ControllerPort


class SimulatorMode(StrEnum):
    AUTO_ACK = "AUTO_ACK"
    DELAYED = "DELAYED"
    SILENT = "SILENT"
    OFFLINE = "OFFLINE"


class RestSimulatorController(ControllerPort):
    """Simulates physical traffic signal controller responses."""

    def __init__(self, mode: SimulatorMode = SimulatorMode.AUTO_ACK) -> None:
        self.mode = mode

    def set_mode(self, mode: SimulatorMode) -> None:
        self.mode = mode

    async def send(self, command: SendSignalCommand) -> bool:
        """Process an outgoing signal command according to current simulator mode."""
        if self.mode in (SimulatorMode.OFFLINE, SimulatorMode.SILENT):
            return False
        # Stub for Phase 0
        return True
