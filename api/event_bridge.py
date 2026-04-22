"""AsyncQueueBus — EventBus-compatible bus that pushes to asyncio Queues.

Thread-safe: emit() uses loop.call_soon_threadsafe() so it can be called
from background ThreadPoolExecutor workers while FastAPI runs its event loop.

Multiple SSE subscribers can call subscribe(); each gets an independent queue
pre-filled with past events so reconnects see the full history.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List


class AsyncQueueBus:
    """Drop-in replacement for EventBus that streams events to SSE clients."""

    def __init__(self, job_id: str, loop: asyncio.AbstractEventLoop):
        self.job_id = job_id
        self._loop = loop
        self._queues: List[asyncio.Queue] = []
        self._events_log: List[Dict[str, Any]] = []   # full history for reconnect

    # ------------------------------------------------------------------
    # EventBus-compatible interface (called from pipeline threads)
    # ------------------------------------------------------------------

    def emit(self, event: str, **kwargs: Any) -> None:
        """Emit an event. Safe to call from any thread."""
        payload: Dict[str, Any] = {
            "type": event,
            "data": dict(kwargs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": self.job_id,
        }
        self._events_log.append(payload)
        # Thread-safe push to every subscriber queue
        for q in list(self._queues):
            self._loop.call_soon_threadsafe(q.put_nowait, payload)

    # ------------------------------------------------------------------
    # SSE subscription (called from async context)
    # ------------------------------------------------------------------

    async def subscribe(self) -> asyncio.Queue:
        """Subscribe to future events. Returns a queue pre-filled with history."""
        q: asyncio.Queue = asyncio.Queue()
        for past_event in self._events_log:
            await q.put(past_event)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    @property
    def events_log(self) -> List[Dict[str, Any]]:
        return list(self._events_log)
