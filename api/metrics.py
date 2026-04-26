"""Prometheus metrics for AegisHarness.

Exposes a /metrics endpoint (text/plain; version=0.0.4) compatible with the
Prometheus scrape protocol.

Metrics
-------
harness_jobs_total{status}            — Counter: jobs by terminal status
harness_task_duration_seconds{agent}  — Histogram: per-agent task latency
harness_llm_tokens_total{agent}       — Counter: LLM tokens consumed per agent
harness_escalations_total{level}      — Counter: resilience escalations by level
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from fastapi import Response

# ---------------------------------------------------------------------------
# Single shared registry (not the default global to avoid cross-test pollution)
# ---------------------------------------------------------------------------

REGISTRY = CollectorRegistry(auto_describe=True)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

jobs_total = Counter(
    "harness_jobs_total",
    "Total jobs by terminal status",
    ["status"],
    registry=REGISTRY,
)

task_duration_seconds = Histogram(
    "harness_task_duration_seconds",
    "Agent task duration in seconds",
    ["agent"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf")),
    registry=REGISTRY,
)

llm_tokens_total = Counter(
    "harness_llm_tokens_total",
    "LLM tokens consumed per agent",
    ["agent"],
    registry=REGISTRY,
)

escalations_total = Counter(
    "harness_escalations_total",
    "Resilience escalations by level",
    ["level"],
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# FastAPI route handler
# ---------------------------------------------------------------------------

async def metrics_endpoint() -> Response:
    """Return current Prometheus metrics in text exposition format."""
    data = generate_latest(REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
