"""REST simulator adapter implementing ControllerPort (D-04).

Supports modes: AUTO_ACK, DELAYED, SILENT, OFFLINE.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any

from app.domain.effects import SendSignalCommand
from app.domain.events import ControllerAck, ControllerNack
from app.domain.ports import ControllerPort


class SimulatorMode(StrEnum):
    AUTO_ACK = "AUTO_ACK"
    DELAYED = "DELAYED"
    SILENT = "SILENT"
    OFFLINE = "OFFLINE"


class RestSimulatorController(ControllerPort):
    """Simulates physical traffic signal controller responses."""

    def __init__(
        self,
        junction_id: str = "A",
        mode: SimulatorMode = SimulatorMode.AUTO_ACK,
        delay_seconds: float = 1.0,
        on_ack: Callable[[ControllerAck], Coroutine[Any, Any, None]] | None = None,
        on_nack: Callable[[ControllerNack], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self.junction_id = junction_id
        self.mode = mode
        self.delay_seconds = delay_seconds
        self.on_ack = on_ack
        self.on_nack = on_nack
        self._background_tasks: set[asyncio.Task[None]] = set()

    def set_mode(self, mode: SimulatorMode) -> None:
        self.mode = mode

    def set_ack_handler(
        self, handler: Callable[[ControllerAck], Coroutine[Any, Any, None]]
    ) -> None:
        self.on_ack = handler

    def set_nack_handler(
        self, handler: Callable[[ControllerNack], Coroutine[Any, Any, None]]
    ) -> None:
        self.on_nack = handler

    async def send(self, command: SendSignalCommand) -> bool:
        """Process an outgoing signal command according to current simulator mode."""
        if self.mode == SimulatorMode.OFFLINE:
            return False

        if self.mode == SimulatorMode.SILENT:
            # Drop command silently without ACK/NACK (causes timeout and retry D-19)
            return True

        if self.mode == SimulatorMode.AUTO_ACK:
            # Emits ACK immediately in a short background task to ensure command returns first
            task = asyncio.create_task(self._deliver_ack(command, delay=0.01))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return True

        if self.mode == SimulatorMode.DELAYED:
            # Deliver ACK after delay
            task = asyncio.create_task(self._deliver_ack(command, delay=self.delay_seconds))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return True

        return True

    async def _deliver_ack(self, command: SendSignalCommand, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        if self.mode in (SimulatorMode.OFFLINE, SimulatorMode.SILENT):
            return  # Cancelled by mode change
        if self.on_ack:
            ack = ControllerAck(
                command_id=command.command_id,
                junction_id=self.junction_id,
                direction=command.direction,
                confirmed_state=command.requested_state,
                server_time=time.time(),
            )
            await self.on_ack(ack)
