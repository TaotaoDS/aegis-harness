"""Job runner: executes the harness pipeline in a background thread.

Bridges the synchronous, blocking pipeline with FastAPI's async event loop:
  - Pipeline runs in ThreadPoolExecutor
  - AsyncQueueBus uses loop.call_soon_threadsafe() to push events to SSE clients
  - HITLManager uses threading.Event to block the pipeline until human approves
  - InterviewManager uses threading.Event to block the pipeline for CEO questions

v0.9.0:
  - CEO interview uses InterviewManager (real user answers, not auto-answer)
  - SolutionStore injects workspace lessons into CEO planning and Architect coding
  - ReflectionAgent runs after every pipeline (success or failure) to distil lessons

v1.0.0:
  - Checkpoint writes at every major phase boundary (file system + optional DB).
    Checkpoints survive process crashes and enable future pipeline resumption.
    Written via WorkspaceManager.save_checkpoint() — never blocks the pipeline.
"""

import asyncio
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
_BOOTSTRAP_TENANT = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# DB helpers (fire-and-forget, never block the pipeline)
# ---------------------------------------------------------------------------

def _db_mirror_status(
    loop: asyncio.AbstractEventLoop,
    job_id: str,
    status: str,
) -> None:
    """Schedule an async DB status update from a background thread."""
    async def _write() -> None:
        try:
            from db.connection import get_session, is_db_available
            from db.repository import update_job_status
            if not is_db_available():
                return
            async with get_session() as session:
                await update_job_status(session, job_id, status)
        except Exception:   # noqa: BLE001
            pass
    try:
        asyncio.run_coroutine_threadsafe(_write(), loop)
    except RuntimeError:
        pass


def _db_mirror_checkpoint(
    loop: asyncio.AbstractEventLoop,
    job_id: str,
    phase: str,
    completed_tasks: Optional[List[str]] = None,
    data: Optional[dict] = None,
) -> None:
    """Schedule an async DB checkpoint upsert from a background thread."""
    async def _write() -> None:
        try:
            from db.connection import get_session, is_db_available
            from db.repository import save_checkpoint
            if not is_db_available():
                return
            async with get_session() as session:
                await save_checkpoint(
                    session,
                    job_id=job_id,
                    phase=phase,
                    completed_tasks=completed_tasks or [],
                    data=data or {},
                )
        except Exception:   # noqa: BLE001
            pass
    try:
        asyncio.run_coroutine_threadsafe(_write(), loop)
    except RuntimeError:
        pass


def _write_checkpoint(
    ws,
    ws_id: str,
    loop: asyncio.AbstractEventLoop,
    job_id: str,
    phase: str,
    completed_tasks: Optional[List[str]] = None,
    extra: Optional[dict] = None,
) -> None:
    """Write a checkpoint to the filesystem (always) and DB (if available).

    Never raises — checkpoint failures must not affect the pipeline.
    """
    from datetime import datetime, timezone
    data = {
        "job_id":           job_id,
        "phase":            phase,
        "completed_tasks":  completed_tasks or [],
        "updated_at":       datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }
    try:
        ws.save_checkpoint(ws_id, data)
    except Exception:   # noqa: BLE001
        pass
    _db_mirror_checkpoint(loop, job_id, phase, completed_tasks, data)


def _load_credit_balance(loop: asyncio.AbstractEventLoop, tenant_id: str) -> Optional[float]:
    """Synchronously fetch tenant credit_balance from DB (called from thread)."""
    result: list = []

    async def _read() -> None:
        try:
            from db.connection import get_session, is_db_available
            from db.repository import get_tenant_credit_balance
            if not is_db_available():
                return
            async with get_session() as session:
                balance = await get_tenant_credit_balance(session, tenant_id)
                result.append(balance)
        except Exception:
            pass

    try:
        future = asyncio.run_coroutine_threadsafe(_read(), loop)
        future.result(timeout=5)
    except Exception:
        pass
    return result[0] if result else None


def _db_flush_billing(
    loop: asyncio.AbstractEventLoop,
    billing_ctx,
) -> None:
    """Persist billing records and deduct tenant credit. Fire-and-forget."""
    if not billing_ctx or not billing_ctx.records:
        return

    async def _write() -> None:
        try:
            from db.connection import get_session, is_db_available
            from db.repository import (
                append_billing_event,
                compute_cost,
                deduct_tenant_credit,
                get_model_pricing,
            )
            if not is_db_available():
                return
            total_cost = 0.0
            async with get_session() as session:
                for rec in billing_ctx.records:
                    pricing = await get_model_pricing(session, rec.model_id)
                    cost = compute_cost(rec.prompt_tokens, rec.completion_tokens, pricing)
                    total_cost += cost
                    await append_billing_event(
                        session,
                        tenant_id=billing_ctx.tenant_id,
                        job_id=billing_ctx.job_id,
                        model_id=rec.model_id,
                        prompt_tokens=rec.prompt_tokens,
                        completion_tokens=rec.completion_tokens,
                        cost_usd=cost,
                    )
                if total_cost > 0:
                    await deduct_tenant_credit(session, billing_ctx.tenant_id, total_cost)
        except Exception:
            pass

    try:
        asyncio.run_coroutine_threadsafe(_write(), loop)
    except RuntimeError:
        pass


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
    bus  = job.bus
    hitl = job.hitl_manager

    if str(_HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(_HARNESS_ROOT))

    # ── Bootstrap ────────────────────────────────────────────────────────
    billing_ctx = None
    try:
        from dotenv import load_dotenv
        load_dotenv(_HARNESS_ROOT / ".env")

        from core_orchestrator.model_router import ModelRouter
        from core_orchestrator.llm_gateway import LLMGateway
        from core_orchestrator.pii_sanitizer import default_pipeline
        from core_orchestrator.workspace_manager import WorkspaceManager
        from core_orchestrator.billing import (
            BillingContext,
            InsufficientCreditError,
            set_billing_context,
        )

        # ── FinOps: install billing context for this pipeline thread ─────
        tenant_id = job.tenant_id or _BOOTSTRAP_TENANT
        credit_balance = _load_credit_balance(loop, tenant_id)
        billing_ctx = BillingContext(
            tenant_id=tenant_id,
            job_id=job.id,
            credit_balance=credit_balance,
        )
        set_billing_context(billing_ctx)

        config_path = _HARNESS_ROOT / "models_config.yaml"
        router    = ModelRouter(config_path)
        sanitizer = default_pipeline()

        llm      = router.as_llm()
        gateway  = LLMGateway(sanitizer=sanitizer, llm=llm)
        tool_llm = router.as_tool_llm()

        ws_root = _HARNESS_ROOT / "workspaces"
        ws = WorkspaceManager(ws_root, isolated=True)
        ws_id = job.workspace_id
        if not ws.exists(ws_id):
            ws.create(ws_id)

        update_status(job.id, "running")
        _db_mirror_status(loop, job.id, "running")
        bus.emit("pipeline.start", workspace=ws_id, job_type=job.type)

        # ── Checkpoint: pipeline started ─────────────────────────────────
        _write_checkpoint(ws, ws_id, loop, job.id, "started")

        # ── Run ──────────────────────────────────────────────────────────
        if job.type == "update":
            _run_update(job, ws, ws_id, gateway, tool_llm, bus, hitl,
                        sanitizer, router, loop=loop)
        else:
            _run_build(job, ws, ws_id, gateway, tool_llm, bus,
                       sanitizer, router, loop=loop)

        update_status(job.id, "completed")
        _db_mirror_status(loop, job.id, "completed")
        bus.emit("pipeline.complete", workspace=ws_id)

        # ── Checkpoint: pipeline completed ───────────────────────────────
        _write_checkpoint(ws, ws_id, loop, job.id, "completed")

    except InsufficientCreditError as e:  # type: ignore[possibly-unbound]
        # Credit exhausted mid-run — treat as a payment-required rejection.
        update_status(job.id, "rejected")
        _db_mirror_status(loop, job.id, "rejected")
        bus.emit("pipeline.rejected", reason=str(e))
        try:
            _write_checkpoint(ws, ws_id, loop, job.id, "rejected",  # type: ignore[possibly-unbound]
                              extra={"reason": "insufficient_credit"})
        except Exception:
            pass

    except _RejectedError as e:
        update_status(job.id, "rejected")
        _db_mirror_status(loop, job.id, "rejected")
        bus.emit("pipeline.rejected", reason=str(e))
        try:
            _write_checkpoint(ws, ws_id, loop, job.id, "rejected")  # type: ignore[possibly-unbound]
        except Exception:
            pass

    except Exception as e:
        update_status(job.id, "failed")
        _db_mirror_status(loop, job.id, "failed")
        bus.emit("pipeline.error", error=str(e),
                 detail=traceback.format_exc()[:800])
        try:
            _write_checkpoint(ws, ws_id, loop, job.id, "failed",  # type: ignore[possibly-unbound]
                              extra={"error": str(e)})
        except Exception:
            pass

    finally:
        # ── FinOps: flush billing records to DB (non-blocking) ───────────
        try:
            from core_orchestrator.billing import set_billing_context
            _db_flush_billing(loop, billing_ctx)
            set_billing_context(None)
        except Exception:
            pass

        # ── Reflection (always runs — failures are most educational) ────
        try:
            _run_reflection(job, ws, ws_id, gateway, bus)   # type: ignore[possibly-unbound]
        except Exception:
            pass   # reflection must never crash the pipeline


# ---------------------------------------------------------------------------
# Build pipeline (greenfield)
# ---------------------------------------------------------------------------

def _run_build(job, ws, ws_id, gateway, tool_llm, bus, sanitizer, router, *, loop):
    from core_orchestrator.ceo_agent import CEOAgent
    from core_orchestrator.solution_store import SolutionStore

    # ── Load workspace solutions (Compound Learning injection) ───────────
    solutions_ctx = SolutionStore(ws, ws_id).format_as_context()

    # ── Resolve user profile ──────────────────────────────────────────────
    user_profile = None
    if job.user_profile:
        from core_orchestrator.user_profile import UserProfile
        try:
            user_profile = UserProfile.from_dict(job.user_profile)
        except Exception:   # noqa: BLE001
            pass   # invalid profile data → fall back to default behaviour

    ceo           = CEOAgent(gateway=gateway, workspace=ws, workspace_id=ws_id,
                             user_profile=user_profile)
    interview_mgr = job.interview_manager   # InterviewManager | None

    # ── CEO interview (95% confidence loop) ─────────────────────────────
    bus.emit("ceo.interviewing")
    _write_checkpoint(ws, ws_id, loop, job.id, "interviewing")

    question = ceo.start_interview(job.requirement)

    while question is not None:
        if interview_mgr:
            # Web mode: block and wait for real user input via POST /answer
            # (InterviewManager emits ceo.question internally)
            answer = interview_mgr.wait_for_answer(question)
        else:
            # Fallback / test mode: auto-answer so the pipeline can proceed
            bus.emit("ceo.question", question=question)
            answer = "Please proceed with the information provided."

        question = ceo.answer_question(answer)

    bus.emit("ceo.interview_complete", confidence=ceo.confidence)
    # ── Checkpoint: interview done ────────────────────────────────────
    _write_checkpoint(ws, ws_id, loop, job.id, "interview_complete",
                      extra={"confidence": ceo.confidence})

    # ── CEO planning (with lessons injected) ────────────────────────────
    bus.emit("ceo.planning")
    plan  = ceo.create_plan(solutions_context=solutions_ctx)
    tasks = plan.get("tasks", [])
    bus.emit("ceo.plan_created", tasks=tasks, task_count=len(tasks))

    bus.emit("ceo.delegating")
    ceo.delegate()
    bus.emit("ceo.delegated", task_count=len(tasks))

    # ── Checkpoint: planning done, about to execute ───────────────────
    task_ids = [t["id"] for t in tasks]
    _write_checkpoint(ws, ws_id, loop, job.id, "executing",
                      completed_tasks=[],
                      extra={"total_tasks": len(tasks), "task_ids": task_ids})

    _run_execution(job, ws, ws_id, tool_llm, bus, sanitizer, router,
                   hitl=job.hitl_manager, solutions_ctx=solutions_ctx,
                   loop=loop)


# ---------------------------------------------------------------------------
# Update pipeline (incremental)
# ---------------------------------------------------------------------------

def _run_update(job, ws, ws_id, gateway, tool_llm, bus, hitl, sanitizer, router, *, loop):
    from core_orchestrator.ceo_agent import CEOAgent
    from core_orchestrator.solution_store import SolutionStore

    solutions_ctx = SolutionStore(ws, ws_id).format_as_context()

    ceo = CEOAgent(gateway=gateway, workspace=ws, workspace_id=ws_id)

    bus.emit("pipeline.update_start", workspace=ws_id)
    _write_checkpoint(ws, ws_id, loop, job.id, "update_planning")

    plan  = ceo.plan_update(job.requirement, solutions_context=solutions_ctx)
    tasks = plan.get("tasks", [])

    if not tasks:
        bus.emit("pipeline.update_complete", task_count=0)
        return

    files_to_modify = list({f for t in tasks for f in t.get("files_to_modify", [])})

    # ── HITL gate 1: approve before any existing code is touched ─────────
    if hitl and not hitl.check_update_mode(job.requirement, files_to_modify):
        raise _RejectedError("User rejected Update Mode execution")

    bus.emit("ceo.plan_created", tasks=tasks, task_count=len(tasks), mode="update")
    bus.emit("ceo.delegating")
    ceo.delegate()
    bus.emit("ceo.delegated", task_count=len(tasks))

    task_ids = [t["id"] for t in tasks]
    _write_checkpoint(ws, ws_id, loop, job.id, "update_executing",
                      completed_tasks=[],
                      extra={"task_ids": task_ids})

    _run_execution(job, ws, ws_id, tool_llm, bus, sanitizer, router,
                   task_ids=task_ids,
                   hitl=hitl,
                   solutions_ctx=solutions_ctx,
                   loop=loop)


# ---------------------------------------------------------------------------
# Execution (shared by build + update)
# ---------------------------------------------------------------------------

def _run_execution(
    job, ws, ws_id, tool_llm, bus, sanitizer, router,
    task_ids: Optional[List[str]] = None,
    hitl: Optional[HITLManager] = None,
    solutions_ctx: str = "",
    loop: Optional[asyncio.AbstractEventLoop] = None,
):
    from core_orchestrator.llm_gateway import LLMGateway
    from core_orchestrator.resilience_manager import ResilienceManager
    from core_orchestrator.knowledge_manager import KnowledgeManager

    _llm       = router.as_llm()
    qa_gateway = LLMGateway(sanitizer=sanitizer, llm=_llm)
    km         = KnowledgeManager(workspace=ws, workspace_id=ws_id)
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
        solutions_context=solutions_ctx,    # ← Compound Learning injection
        bus=bus,
        hitl_manager=hitl,
    )

    results  = [rm.run_task_loop(tid) for tid in task_ids] if task_ids else rm.run_all()
    passed   = sum(1 for r in results if r.get("verdict") == "pass")
    escalated = len(results) - passed

    bus.emit(
        "pipeline.execution_complete",
        passed=passed,
        escalated=escalated,
        total=len(results),
        results=[{"task_id": r["task_id"], "verdict": r["verdict"]} for r in results],
    )

    # ── Checkpoint: execution done ────────────────────────────────────
    if loop:
        completed = [r["task_id"] for r in results if r.get("verdict") == "pass"]
        _write_checkpoint(ws, ws_id, loop, job.id, "execution_complete",
                          completed_tasks=completed,
                          extra={"passed": passed, "escalated": escalated})


# ---------------------------------------------------------------------------
# Reflection (always runs after pipeline completes or fails)
# ---------------------------------------------------------------------------

def _run_reflection(job, ws, ws_id, gateway, bus) -> None:
    """Run ReflectionAgent to distil lessons from this job's event log."""
    from core_orchestrator.reflection_agent import ReflectionAgent

    events_snapshot = list(bus.events_log)   # snapshot — pipeline is done
    ra = ReflectionAgent(gateway=gateway, workspace=ws, workspace_id=ws_id)
    ra.reflect(
        events_log=events_snapshot,
        requirement=job.requirement,
        job_id=job.id,
        bus=bus,
    )


class _RejectedError(Exception):
    pass
