"""Domain effects definitions (outputs returned by the traffic engine).

Reference: Instruction.md section 5.1 and Decision.md D-02.
Pure data definitions describing actions to be executed by the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.types import Direction, Signal


@dataclass(slots=True)
class SendSignalCommand:
    command_id: str
    direction: Direction
    requested_state: Signal


@dataclass(slots=True)
class RecordAudit:
    event_type: str
    direction: Direction | None = None
    previous_state: Signal | None = None
    new_state: Signal | None = None
    command_id: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScheduleNothing:
    pass


@dataclass(slots=True)
class Alert:
    alert_type: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# Union type for all possible engine effects
DomainEffect = SendSignalCommand | RecordAudit | ScheduleNothing | Alert
