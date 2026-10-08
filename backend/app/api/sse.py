"""Server-Sent Events endpoint handler per contracts/sse.md.

Owned by Agent B (Phase 1).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Request


async def event_generator(junction_id: str, request: Request) -> AsyncGenerator[str, None]:
    """Yield SSE formatted events (: ping and event: status)."""
    # Stub for Phase 0
    yield ": ping\n\n"
