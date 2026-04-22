"""Job runner: executes the harness pipeline in a background thread.

Bridges the synchronous, blocking pipeline with FastAPI's async event loop:
- Pipeline runs in ThreadPoolExecutor
- AsyncQueueBus uses loop.call_soon_threadsafe() to push events to SSE clients
- HITLManager uses threading.Event to block the pipeline until human approves
"""

import asyncio
import json
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from .event_bridge import AsyncQueueBus
from .hitl_manager import HITLManager
from .job_store import JobRecord, update_status

_HARNESS_ROOT = Path(__file__).parent.parent
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="harness-job")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_job(job: JobRecord, loop: asyncio.AbstractEventLoop) -> None:
    """Submit job to the background thread pool. Non-blocking."""
    _executor.submit(_run_pipeline, job, loop)


# ---------------------------------------------------------------------------
# Pipeline thread (blocking — runs in ThreadPoolExecutor)
# ---------------------------------------------------------------------------

def _run_pipeline(job: JobRecord, loop: asyncio.AbstractEventLoop) -> None:
    bus = job.bus
    hitl = job.hitl_manager

    if str(_HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(_HARNESS_ROOT))

    try:
        from dotenv import load_dotenv
        load_dotenv(_HARNESS_ROOT / ".env")

        from core_orchestrator.model_router import ModelRouter
        from core_orchestrator.llm_gateway import LLMGateway
        from core_orchestrator.pii_sanitizer import default_pipeline
        from core_orchestrator.workspace_manager import WorkspaceManager

        config_path = _HARNESS_ROOT / "models_config.yaml"
        router = ModelRouter(config_path)
        sanitizer = default_pipeline()

        llm = router.as_llm()
        gateway = LLMGateway(sanitizer=sanitizer, llm=llm)
        tool_llm = router.as_tool_llm()

        ws_root = _HARNESS_ROOT / "workspaces"
        ws = WorkspaceManager(ws_root, isolated=True)
        ws_id = job.workspace_id
        if not ws.exists(ws_id):
            ws.create(ws_id)

        update_status(job.id, "running")
        bus.emit("pipeline.start", workspace=ws_id, job_type=job.type)

        if job.type == "update":
            _run_update(job, ws, ws_id, gateway, tool_llm, bus, hitl, sanitizer, router)
        else:
            _run_build(job, ws, ws_id, gateway, tool_llm, bus, sanitizer, router)

        update_status(job.id, "completed")
        bus.emit("pipeline.complete", workspace=ws_id)

    except _RejectedError as e:
        update_status(job.id, "rejected")
        bus.emit("pipeline.rejected", reason=str(e))
    except Exception as e:
        update_status(job.id, "failed")
        bus.emit("pipeline.error", error=str(e), detail=traceback.format_exc()[:800])


# ---------------------------------------------------------------------------
# Build pipeline (greenfield)
# ---------------------------------------------------------------------------

def _run_build(job, ws, ws_id, gateway, tool_llm, bus, sanitizer, router):
    from core_orchestrator.ceo_agent import CEOAgent

    ceo = CEOAgent(gateway=gateway, workspace=ws, workspace_id=ws_id)

    # Auto-interview: answer all CEO questions automatically
    bus.emit("ceo.interviewing")
    question = ceo.start_interview(job.requirement)
    while question is not None:
        bus.emit("ceo.question", question=question)
        question = ceo.answer_question("Please proceed with the information provided.")

    bus.emit("ceo.planning")
    plan = ceo.create_plan()
    tasks = plan.get("tasks", [])
    bus.emit("ceo.plan_created", tasks=tasks, task_count=len(tasks))

    bus.emit("ceo.delegating")
    ceo.delegate()
    bus.emit("ceo.delegated", task_count=len(tasks))

    _run_execution(job, ws, ws_id, tool_llm, bus, sanitizer, router,
                   hitl=job.hitl_manager)


# ---------------------------------------------------------------------------
# Update pipeline (incremental)
# ---------------------------------------------------------------------------

def _run_update(job, ws, ws_id, gateway, tool_llm, bus, hitl, sanitizer, router):
    from core_orchestrator.ceo_agent import CEOAgent

    ceo = CEOAgent(gateway=gateway, workspace=ws, workspace_id=ws_id)

    bus.emit("pipeline.update_start", workspace=ws_id)
    plan = ceo.plan_update(job.requirement)
    tasks = plan.get("tasks", [])

    if not tasks:
        bus.emit("pipeline.update_complete", task_count=0)
        return

    files_to_modify = list({f for t in tasks for f in t.get("files_to_modify", [])})

    # ── HITL gate 1: approve before any existing code is touched ──────────
    if hitl and not hitl.check_update_mode(job.requirement, files_to_modify):
        raise _RejectedError("User rejected Update Mode execution")

    bus.emit("ceo.plan_created", tasks=tasks, task_count=len(tasks), mode="update")
    bus.emit("ceo.delegating")
    ceo.delegate()
    bus.emit("ceo.delegated", task_count=len(tasks))

    _run_execution(job, ws, ws_id, tool_llm, bus, sanitizer, router,
                   task_ids=[t["id"] for t in tasks],
                   hitl=hitl)


# ---------------------------------------------------------------------------
# Execution (shared by build + update)
# ---------------------------------------------------------------------------

def _run_execution(
    job, ws, ws_id, tool_llm, bus, sanitizer, router,
    task_ids: Optional[List[str]] = None,
    hitl: Optional[HITLManager] = None,
):
    from core_orchestrator.llm_gateway import LLMGateway
    from core_orchestrator.resilience_manager import ResilienceManager
    from core_orchestrator.knowledge_manager import KnowledgeManager

    _llm = router.as_llm()
    qa_gateway = LLMGateway(sanitizer=sanitizer, llm=_llm)
    km = KnowledgeManager(workspace=ws, workspace_id=ws_id)
    knowledge_ctx = km.load_knowledge()

    rm = ResilienceManager(
        workspace=ws,
        workspace_id=ws_id,
        tool_llm=tool_llm,
        qa_gateway=qa_gateway,
        max_retries=3,
        token_budget=100_000,
        token_threshold=0.8,
        eval_timeout=30,
        knowledge_manager=km,
        knowledge_context=knowledge_ctx,
        bus=bus,
        hitl_manager=hitl,      # ← injected into ArchitectAgent
    )

    if task_ids:
        results = [rm.run_task_loop(tid) for tid in task_ids]
    else:
        results = rm.run_all()

    passed = sum(1 for r in results if r.get("verdict") == "pass")
    escalated = len(results) - passed
    bus.emit(
        "pipeline.execution_complete",
        passed=passed,
        escalated=escalated,
        total=len(results),
        results=[{"task_id": r["task_id"], "verdict": r["verdict"]} for r in results],
    )


class _RejectedError(Exception):
    pass
