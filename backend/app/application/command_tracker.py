"""Command lifecycle and retry tracker (D-19).

Handles ACK timeout, same-command_id retries, duplicate ACK, and degraded mode trigger.
Owned by Agent C (Phase 1).
"""

from __future__ import annotations


class CommandTracker:
    """Tracks outstanding controller commands and retry limits."""

    def __init__(self, ack_timeout: float = 3.0, max_retries: int = 2) -> None:
        self.ack_timeout = ack_timeout
        self.max_retries = max_retries

    def record_command_sent(self, command_id: str, sent_at: float) -> None:
        """Register a command sent to the controller."""
        pass

    def record_ack(self, command_id: str, acked_at: float) -> bool:
        """Process ACK. Return True if valid and timely, False if duplicate or late."""
        return True
