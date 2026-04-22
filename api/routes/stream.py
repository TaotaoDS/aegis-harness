"""SSE streaming endpoint.

GET /jobs/{job_id}/stream
  → text/event-stream, one JSON object per event line
  → Replays full history on connect (reconnect-safe)
  → Sends keepalive comments every 15 s to prevent proxy timeouts
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..event_labels import translate
from ..job_store import get_job

router = APIRouter(prefix="/jobs", tags=["stream"])

_KEEPALIVE_INTERVAL = 15  # seconds


@router.get("/{job_id}/stream")
async def stream_events(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.bus:
        raise HTTPException(status_code=409, detail="Job bus not initialised")

    queue = await job.bus.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                    # Enrich with human-readable label
                    payload["label"] = translate(payload["type"], payload.get("data", {}))
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                    # Stop after terminal events
                    if payload["type"] in {
                        "pipeline.complete", "pipeline.error",
                        "pipeline.rejected",
                    }:
                        break

                except asyncio.TimeoutError:
                    # SSE keepalive comment
                    yield ": keepalive\n\n"

        finally:
            job.bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )


@router.get("/{job_id}/events")
async def get_past_events(job_id: str):
    """Return full event history snapshot (for initial page load / reconnect)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.bus:
        return []
    events = job.bus.events_log
    for e in events:
        e["label"] = translate(e["type"], e.get("data", {}))
    return events
