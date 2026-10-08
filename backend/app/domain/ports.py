"""Domain ports (interfaces for external capabilities).

Reference: Instruction.md section 5.1 and Decision.md D-02, D-04.
The pure domain engine receives IDs and timestamps from callers or ports.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.effects import SendSignalCommand


class ControllerPort(Protocol):
    """Port for communicating with physical or simulated traffic signal controllers."""

    async def send(self, command: SendSignalCommand) -> bool:
        """Send a signal command to the controller."""
        ...


class Clock(Protocol):
    """Port providing monotonic or current epoch timestamp."""

    def now(self) -> float:
        """Return current server time in seconds."""
        ...


class IdGenerator(Protocol):
    """Port providing unique identifiers."""

    def new_command_id(self) -> str:
        """Generate a unique command identifier (e.g. cmd-xxxx)."""
        ...
