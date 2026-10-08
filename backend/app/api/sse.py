"""Server-Sent Events endpoint handler per contracts/sse.md.

Owned by Agent B (Phase 1).
Yields:
- Immediate full status event on connection
- Subsequent status events on every committed state change
- Heartbeat ': ping\\n\\n' every 15 seconds (P-03)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.application.junction_worker import JunctionWorker

logger = logging.getLogger("factory_traffic.sse")


async def sse_event_generator(
    worker: JunctionWorker, request: Request
) -> AsyncGenerator[str, None]:
    """Yield SSE formatted events for a junction."""
    # 1. Immediately emit current junction status snapshot
    initial_status = worker.get_status_dict()
    yield f"event: status\ndata: {json.dumps(initial_status)}\n\n"

    # 2. Subscribe to worker's state broadcast queue
    import time

    last_ping = time.time()
    sub_queue = worker.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break

            try:
                status_payload = await asyncio.wait_for(sub_queue.get(), timeout=0.2)
                yield f"event: status\ndata: {json.dumps(status_payload)}\n\n"
            except TimeoutError:
                now = time.time()
                if now - last_ping >= 15.0:
                    yield ": ping\n\n"
                    last_ping = now
    except (asyncio.CancelledError, GeneratorExit):
        pass
    except Exception as exc:
        logger.debug("SSE connection ended for junction %s: %s", worker.junction_id, exc)
    finally:
        worker.unsubscribe(sub_queue)
