"""FastAPI application entrypoint.

Reference: Instruction.md 3, 5.3.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import AppError, app_error_handler
from app.api.routers import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    # Startup: Agent C registers workers and boot recovery here
    yield
    # Shutdown: cleanup workers and tasks


def create_app() -> FastAPI:
    app = FastAPI(
        title="Factory Traffic Management System",
        description="Event-driven factory traffic control system.",
        version="0.1.0",
        lifespan=lifespan,
    )

    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)

    return app


app = create_app()
