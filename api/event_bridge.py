"""AsyncQueueBus — EventBus-compatible bus that pushes to asyncio Queues.

Thread-safe: emit() uses loop.call_soon_threadsafe() so it can be called
from background ThreadPoolExecutor workers while FastAPI runs its event loop.

Multiple SSE subscribers can call subscribe(); each gets an independent queue
pre-filled with past events so reconnects see the full history.

DB persistence
--------------
When a PostgreSQL database is available (``db.connection.is_db_available()``),
each emitted event is also persisted asynchronously via
``asyncio.run_coroutine_threadsafe()``.  This is fire-and-forget: a DB
failure never blocks or crashes the pipeline.
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
        seq = len(self._events_log)
        self._events_log.append(payload)

        # Thread-safe push to every SSE subscriber queue
        for q in list(self._queues):
            self._loop.call_soon_threadsafe(q.put_nowait, payload)

        # ── Optional DB persistence (fire-and-forget) ────────────────────
        self._persist_event_to_db(payload, seq)

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist_event_to_db(self, payload: Dict[str, Any], seq: int) -> None:
        """Schedule an async DB write for a single event (fire-and-forget).

        Called from emit() which may run on a background thread, so we
        use run_coroutine_threadsafe to cross the sync/async boundary.
        """
        try:
            from db.connection import is_db_available  # lazy import
        except ImportError:
            return

        if not is_db_available():
            return

        job_id = self.job_id

        async def _write() -> None:
            try:
                from db.connection import get_session
                from db.repository import append_event
                async with get_session() as session:
                    await append_event(session, job_id, seq, payload)
            except Exception:   # noqa: BLE001
                pass            # DB failures must never affect the pipeline

        try:
            asyncio.run_coroutine_threadsafe(_write(), self._loop)
        except RuntimeError:
            pass   # loop may be closed during shutdown
