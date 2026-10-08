"""Periodic tick emitter (P-03).

Emits Tick events every 500ms into the junction queue.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger("factory_traffic.ticker")


class Ticker:
    """Emits periodic ticks to drive signal deadlines."""

    def __init__(
        self,
        interval_seconds: float = 0.5,
        on_tick: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.on_tick = on_tick
        self._running = False
        self._task: asyncio.Task[None] | None = None

    def set_on_tick(self, handler: Callable[[], Coroutine[Any, Any, None]]) -> None:
        self.on_tick = handler

    async def start(self) -> None:
        """Start emitting periodic ticks."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Stop emitting periodic ticks."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                if self._running and self.on_tick is not None:
                    await self.on_tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error in ticker loop: %s", exc)
