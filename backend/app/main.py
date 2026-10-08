"""FastAPI application entrypoint.

Reference: Instruction.md 3, 5.3.
Wires API routers, CORS, exception handlers, and application lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import AppError, app_error_handler, validation_error_handler
from app.api.routers import router
from app.application.junction_worker import get_junction_manager
from app.domain.types import Direction, JunctionConfig, Phase, TimingsConfig
from app.infrastructure.db.repositories import JunctionRepository
from app.infrastructure.db.session import async_session_factory, init_tables
from app.seed import seed_junction_a

logger = logging.getLogger("factory_traffic.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    try:
        await init_tables()
        await seed_junction_a()
        manager = get_junction_manager()
        async with async_session_factory() as session:
            repo = JunctionRepository(session)
            junctions = await repo.list_all()
            for j in junctions:
                cfg = j.config
                phases = {
                    Phase(p): [Direction(d) for d in dirs]
                    for p, dirs in cfg.get("phases", {}).items()
                }
                timings_dict = cfg.get("timings", {})
                timings = TimingsConfig(**timings_dict) if timings_dict else TimingsConfig()
                domain_config = JunctionConfig(
                    id=j.id,
                    name=j.name,
                    phases=phases,
                    timings=timings,
                )
                manager.register_junction(domain_config)
        await manager.start_all()
        logger.info("Application startup completed successfully.")
    except Exception as exc:
        logger.warning(
            "Startup initialization encountered an error (ensure DB is available): %s", exc
        )

    yield

    try:
        manager = get_junction_manager()
        await manager.stop_all()
        logger.info("Application shutdown completed.")
    except Exception as exc:
        logger.warning("Error during application shutdown: %s", exc)


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
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.include_router(router)

    return app


app = create_app()
