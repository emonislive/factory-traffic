"""Command lifecycle and retry tracker (D-19).

Handles ACK timeout (3s), same-command_id retries (max 2), duplicate ACK,
and degraded mode triggers.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.effects import SendSignalCommand
from app.domain.types import Direction, Signal


@dataclass(slots=True)
class TrackedCommand:
    command_id: str
    junction_id: str
    direction: Direction
    requested_state: Signal
    sent_at: float
    deadline_at: float
    attempts: int = 1
    status: str = "PENDING"  # PENDING, ACKED, FAILED, ABANDONED


class CommandTracker:
    """Tracks outstanding controller commands and retry limits (D-19)."""

    def __init__(self, ack_timeout: float = 3.0, max_retries: int = 2) -> None:
        self.ack_timeout = ack_timeout
        self.max_retries = max_retries
        self._commands: dict[str, TrackedCommand] = {}

    def record_command_sent(
        self, command: SendSignalCommand, junction_id: str, sent_at: float
    ) -> TrackedCommand:
        """Register a command sent to the controller."""
        if command.command_id in self._commands:
            return self._commands[command.command_id]

        tracked = TrackedCommand(
            command_id=command.command_id,
            junction_id=junction_id,
            direction=command.direction,
            requested_state=command.requested_state,
            sent_at=sent_at,
            deadline_at=sent_at + self.ack_timeout,
            attempts=1,
            status="PENDING",
        )
        self._commands[command.command_id] = tracked
        return tracked

    def record_ack(
        self, command_id: str, acked_at: float
    ) -> tuple[bool, Literal["OK", "DUPLICATE", "UNKNOWN", "LATE"]]:
        """Process ACK.

        Return (is_valid, reason):
        - (True, "OK"): Timely first ACK.
        - (False, "DUPLICATE"): Already ACKed.
        - (False, "LATE"): ACK received after deadline or after being marked failed.
        - (False, "UNKNOWN"): Command ID not found.
        """
        tracked = self._commands.get(command_id)
        if tracked is None:
            return False, "UNKNOWN"

        if tracked.status == "ACKED":
            return False, "DUPLICATE"

        if tracked.status in ("FAILED", "ABANDONED"):
            return False, "LATE"

        if acked_at > tracked.deadline_at and tracked.attempts >= self.max_retries:
            tracked.status = "FAILED"
            return False, "LATE"

        tracked.status = "ACKED"
        return True, "OK"

    def check_timeouts(self, now: float) -> list[tuple[TrackedCommand, bool]]:
        """Find commands that have exceeded their deadline.

        Returns list of (command, can_retry).
        """
        timed_out: list[tuple[TrackedCommand, bool]] = []
        for cmd in self._commands.values():
            if cmd.status == "PENDING" and now >= cmd.deadline_at:
                can_retry = cmd.attempts < self.max_retries
                timed_out.append((cmd, can_retry))
        return timed_out

    def record_retry(self, command_id: str, now: float) -> TrackedCommand | None:
        """Increment attempt count and update deadline for a retry."""
        cmd = self._commands.get(command_id)
        if cmd is not None:
            cmd.attempts += 1
            cmd.deadline_at = now + self.ack_timeout
        return cmd

    def mark_failed(self, command_id: str) -> None:
        cmd = self._commands.get(command_id)
        if cmd is not None:
            cmd.status = "FAILED"

    def get_pending(self) -> list[TrackedCommand]:
        return [cmd for cmd in self._commands.values() if cmd.status == "PENDING"]

    def abandon_all(self) -> None:
        """Mark all pending commands as ABANDONED (for restart recovery D-20)."""
        for cmd in self._commands.values():
            if cmd.status == "PENDING":
                cmd.status = "ABANDONED"
