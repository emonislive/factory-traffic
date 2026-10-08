"""Async database repositories.

Owned by Agent B (Phase 1).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class JunctionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class VehicleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class ProcessedEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class CommandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, entry: Any) -> None:
        """Append an audit entry (append-only; no update/delete)."""
        pass


class DeviceStatusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
