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


_MAX_QUEUE_SIZE = 200
_RECONNECT_HISTORY_LIMIT = 50


class AsyncQueueBus:
    """Drop-in replacement for EventBus that streams events to SSE clients.

    Enhancements over basic queue bus:
    - Monotonic sequence IDs (``seq``) for reliable frontend deduplication
    - Bounded subscriber queues (backpressure: drops oldest on overflow)
    - Reconnect history limited to recent events for fast reconnection
    - Lightweight event payloads (large data fields trimmed for non-rich events)
    """

    def __init__(self, job_id: str, loop: asyncio.AbstractEventLoop):
        self.job_id = job_id
        self._loop = loop
        self._queues: List[asyncio.Queue] = []
        self._events_log: List[Dict[str, Any]] = []
        self._seq = 0

    # ------------------------------------------------------------------
    # EventBus-compatible interface (called from pipeline threads)
    # ------------------------------------------------------------------

    _RICH_EVENT_PREFIXES = frozenset({
        "ceo.plan_created", "architect.file_written",
        "qa.pass", "qa.fail", "evaluator.pass", "evaluator.fail",
    })

    def emit(self, event: str, **kwargs: Any) -> None:
        """Emit an event. Safe to call from any thread."""
        data = dict(kwargs)

        # Trim large data fields for non-rich events to reduce SSE bandwidth
        if not any(event.startswith(p) for p in self._RICH_EVENT_PREFIXES):
            for key in list(data):
                val = data[key]
                if isinstance(val, str) and len(val) > 500:
                    data[key] = val[:500] + "…"

        payload: Dict[str, Any] = {
            "seq": self._seq,
            "type": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job_id": self.job_id,
        }
        self._seq += 1
        self._events_log.append(payload)

        for q in list(self._queues):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, payload)
            except asyncio.QueueFull:
                # Backpressure: discard oldest event from slow subscriber
                try:
                    self._loop.call_soon_threadsafe(q.get_nowait)
                    self._loop.call_soon_threadsafe(q.put_nowait, payload)
                except Exception:
                    pass

        self._persist_event_to_db(payload, self._seq - 1)

    # ------------------------------------------------------------------
    # SSE subscription (called from async context)
    # ------------------------------------------------------------------

    async def subscribe(self) -> asyncio.Queue:
        """Subscribe to future events. Returns a bounded queue with recent history."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        history = self._events_log[-_RECONNECT_HISTORY_LIMIT:]
        for past_event in history:
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
