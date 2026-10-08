"""Periodic tick emitter (P-03).

Emits Tick events every 500ms into the junction queue.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


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

    async def start(self) -> None:
        """Start emitting periodic ticks."""
        self._running = True

    async def stop(self) -> None:
        """Stop emitting periodic ticks."""
        self._running = False
        if self._task:
            self._task.cancel()
