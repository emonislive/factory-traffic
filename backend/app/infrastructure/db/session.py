"""Database engine and async session provider."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infrastructure.db.models import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/factory_traffic",
)


def create_engine_for_url(url: str) -> AsyncEngine:
    connect_args: dict[str, Any] = {}
    if "sqlite" in url:
        connect_args["check_same_thread"] = False
    new_engine = create_async_engine(url, echo=False, connect_args=connect_args)
    if "sqlite" in url:
        @event.listens_for(new_engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return new_engine


engine: AsyncEngine = create_engine_for_url(DATABASE_URL)
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


def set_engine(new_engine: AsyncEngine) -> None:
    global engine, async_session_factory
    engine = new_engine
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def init_tables(bind_engine: AsyncEngine | None = None) -> None:
    """Initialize database tables from Base metadata if not yet created."""
    target_engine = bind_engine or engine
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for obtaining an async database session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session

