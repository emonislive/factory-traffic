"""Pure domain traffic engine (state machine in Instruction.md 5.2, D-02).

Engine signature: (state, event, now) -> (new_state, effects).
No I/O, no DB, no HTTP, no datetime.now().
Owned by Agent A (Phase 1).
"""

from __future__ import annotations

from typing import Any

from app.domain.effects import DomainEffect
from app.domain.types import JunctionConfig, JunctionState


def process_event(
    state: JunctionState,
    config: JunctionConfig,
    event: Any,
    now: float,
) -> tuple[JunctionState, list[DomainEffect]]:
    """Transition state given an incoming event and return effects.

    Stub for Phase 0.
    """
    # Stub: no business logic in Phase 0
    return state, []
