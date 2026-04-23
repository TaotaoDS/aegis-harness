"""AegisHarness — CLI entry point with checkpoint resume.

Full pipeline:
    CEO (interview → plan → delegate)
    → ResilienceManager (Architect ↔ QA loop with 3-layer escalation)
    → CE Orchestrator (5 sub-agent post-mortem)

Checkpoint stages (saved to checkpoint.json in workspace):
    interviewed → delegated → executed → postmortem

On re-run, the pipeline reads checkpoint.json and skips completed stages.

Usage:
    python main.py                          # default workspace
    python main.py --workspace my_project   # custom workspace id
    python main.py --reset                  # discard checkpoint, start fresh
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml
from dotenv import load_dotenv

# Load .env at process start so every component (ModelRouter, direct env reads,
# third-party SDK auto-detection) sees the variables immediately.
# A .env file is optional — if absent, shell env vars are used as-is.
load_dotenv()

from core_orchestrator.llm_gateway import LLMGateway
from core_orchestrator.pii_sanitizer import default_pipeline
from core_orchestrator.workspace_manager import WorkspaceManager
from core_orchestrator.ceo_agent import CEOAgent
from core_orchestrator.resilience_manager import ResilienceManager
from core_orchestrator.ce_orchestrator import CEOrchestrator
from core_orchestrator.knowledge_manager import KnowledgeManager
from core_orchestrator.solution_store import SolutionStore
from core_orchestrator.reflection_agent import ReflectionAgent
from core_orchestrator.event_bus import EventBus, NullBus, bus_from_workspace


WORKSPACE_ROOT = Path(__file__).parent / "workspaces"
DEFAULT_WORKSPACE_ID = "default"
KB_PATH = Path(__file__).parent / "knowledge_base" / "project_workspaces" / "Project_A" / "docs" / "solutions"

CHECKPOINT_FILE = "checkpoint.json"

# Stage ordering — each stage implies all previous stages are complete
STAGES = ["interviewed", "delegated", "executed", "postmortem"]


# ---------------------------------------------------------------------------
# Checkpoint: save / load
# ---------------------------------------------------------------------------

def save_checkpoint(
    workspace: WorkspaceManager,
    workspace_id: str,
    *,
    stage: str,
    requirement: str,
    execution_status: Optional[Dict] = None,
) -> None:
    """Write checkpoint.json to the workspace directory."""
    data = {
        "stage": stage,
        "requirement": requirement,
        "execution_status": execution_status,
    }
    workspace.write(workspace_id, CHECKPOINT_FILE, json.dumps(data, indent=2))


def load_checkpoint(
    workspace: WorkspaceManager,
    workspace_id: str,
) -> Optional[Dict]:
    """Read checkpoint.json from workspace. Returns None if not found."""
    if not workspace.exists(workspace_id, CHECKPOINT_FILE):
        return None
    raw = workspace.read(workspace_id, CHECKPOINT_FILE)
    return json.loads(raw)


def _stage_done(checkpoint: Optional[Dict], stage: str) -> bool:
    """Check if a stage has already been completed according to checkpoint."""
    if checkpoint is None:
        return False
    cp_stage = checkpoint.get("stage", "")
    if cp_stage not in STAGES:
        return False
    return STAGES.index(cp_stage) >= STAGES.index(stage)


# ---------------------------------------------------------------------------
# Phase 1: CEO — interview, plan, delegate
# ---------------------------------------------------------------------------

def build_pipeline(
    *,
    workspace_root: Optional[Path] = None,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    llm: Optional[Callable[[str], str]] = None,
) -> CEOAgent:
    """Assemble the orchestration pipeline and return a ready CEOAgent."""
    root = workspace_root or WORKSPACE_ROOT
    ws = WorkspaceManager(root, isolated=True)

    if not ws.exists(workspace_id):
        ws.create(workspace_id)

    sanitizer = default_pipeline()

    if llm is None:
        from core_orchestrator.model_router import ModelRouter

        config_path = Path(__file__).parent / "models_config.yaml"
        router = ModelRouter(config_path)
        llm = router.as_llm()

    gateway = LLMGateway(sanitizer=sanitizer, llm=llm)
    return CEOAgent(gateway=gateway, workspace=ws, workspace_id=workspace_id)


def run_interview_loop(
    ceo: CEOAgent,
    requirement: str,
    solutions_context: str = "",
) -> None:
    """Drive the CEO through interview (95% confidence) → plan → delegate-ready.

    In CLI mode the user types answers directly. The CEO's confidence score
    is shown after each round so the user can see progress.
    """
    question = ceo.start_interview(requirement)

    while question is not None:
        print(f"\n[CEO] Q: {question}")
        answer = input("[You] > ")
        question = ceo.answer_question(answer)
        conf = ceo.confidence
        if conf > 0:
            print(f"[CEO] Confidence: {conf}%")

    print(f"\n[CEO] Interview complete (confidence: {ceo.confidence}%). Generating plan...")
    plan = ceo.create_plan(solutions_context=solutions_context)

    task_count = len(plan.get("tasks", []))
    print(f"[CEO] Plan created with {task_count} task(s).")
    for task in plan.get("tasks", []):
        print(f"  - [{task['priority']}] {task['id']}: {task['title']}")


# ---------------------------------------------------------------------------
# Phase 2: ResilienceManager — Architect ↔ QA loop with escalation
# ---------------------------------------------------------------------------

def _load_execution_config() -> Dict:
    """Read execution parameters from models_config.yaml."""
    config_path = Path(__file__).parent / "models_config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("execution", {})
    return {}


def run_execution(
    *,
    workspace: WorkspaceManager,
    workspace_id: str,
    llm: Optional[Callable[[str], str]] = None,
    tool_llm=None,
    escalated_tool_llm=None,
    bus=None,
    solutions_context: str = "",
) -> Dict:
    """Run Architect + Evaluator + QA on all delegated tasks via ResilienceManager.

    The Architect uses Tool Use (Function Calling) via tool_llm.
    QA uses a standard text gateway via llm.

    Returns the ResilienceManager.status() dict:
        {"completed": [...], "escalated": [...], "token_usage": int}
    """
    sanitizer = default_pipeline()
    exec_cfg = _load_execution_config()

    _llm = llm or _load_default_llm()
    _tool_llm = tool_llm or _make_tool_llm_from_text_llm(_llm)
    _esc_tool_llm = escalated_tool_llm or _tool_llm

    qa_gateway = LLMGateway(sanitizer=sanitizer, llm=_llm)

    # Knowledge base
    km = KnowledgeManager(workspace=workspace, workspace_id=workspace_id)
    knowledge_ctx = km.load_knowledge()

    rm = ResilienceManager(
        workspace=workspace,
        workspace_id=workspace_id,
        tool_llm=_tool_llm,
        qa_gateway=qa_gateway,
        max_retries=exec_cfg.get("max_retries", 3),
        token_budget=exec_cfg.get("token_budget", 100_000),
        token_threshold=exec_cfg.get("token_threshold", 0.8),
        eval_timeout=exec_cfg.get("eval_timeout", 30),
        knowledge_manager=km,
        knowledge_context=knowledge_ctx,
        solutions_context=solutions_context,
        bus=bus,
        escalated_tool_llm=_esc_tool_llm,
    )

    print("\n[Execution] Running Architect + Evaluator + QA pipeline...")
    results = rm.run_all()

    for r in results:
        tag = "PASS" if r["verdict"] == "pass" else "ESCALATED"
        attempts = r["attempts"]
        print(f"  [{tag}] {r['task_id']} (attempts: {attempts}) -> {r['path']}")

    status = rm.status()
    passed = len(status["completed"])
    escalated = len(status["escalated"])
    print(f"[Execution] Done: {passed} passed, {escalated} escalated, "
          f"tokens used: {status['token_usage']}")

    return status


# ---------------------------------------------------------------------------
# Phase 3a: Reflection Agent — workspace-scoped Compound Learning
# ---------------------------------------------------------------------------

def run_reflection(
    *,
    workspace: WorkspaceManager,
    workspace_id: str,
    requirement: str,
    llm: Optional[Callable[[str], str]] = None,
    bus=None,
) -> int:
    """Run ReflectionAgent on the current bus/event log to distil lessons.

    Returns the number of solutions saved to workspaces/{ws_id}/solutions/.
    """
    sanitizer = default_pipeline()
    _llm = llm or _load_default_llm()
    gateway = LLMGateway(sanitizer=sanitizer, llm=_llm)

    # Collect events from bus (EventBus stores them in .events list)
    events_log: List[Dict] = []
    if bus and hasattr(bus, "events"):
        events_log = list(bus.events)

    ra = ReflectionAgent(
        gateway=gateway,
        workspace=workspace,
        workspace_id=workspace_id,
    )
    count = ra.reflect(events_log=events_log, requirement=requirement)
    print(f"[Reflection] Distilled {count} lesson(s) → workspaces/{workspace_id}/solutions/")
    return count


# ---------------------------------------------------------------------------
# Phase 3b: CE Orchestrator — post-mortem knowledge capture
# ---------------------------------------------------------------------------

def run_postmortem(
    *,
    workspace: WorkspaceManager,
    workspace_id: str,
    llm: Optional[Callable[[str], str]] = None,
    knowledge_base_path: Optional[str] = None,
) -> List[Dict]:
    """Run the CE Orchestrator on all tasks that have artifacts.

    Returns a list of merged analysis dicts, one per task.
    """
    sanitizer = default_pipeline()
    _llm = llm or _load_default_llm()
    gateway = LLMGateway(sanitizer=sanitizer, llm=_llm)

    kb = knowledge_base_path or str(KB_PATH)

    ce = CEOrchestrator(
        gateway=gateway,
        workspace=workspace,
        workspace_id=workspace_id,
        knowledge_base_path=kb,
    )

    print("\n[CE] Running post-mortem analysis...")
    results = ce.analyze_all()

    for r in results:
        tid = r["task_id"]
        severity = r.get("context_analysis", {}).get("severity", "?")
        action = r.get("doc_search", {}).get("action", "?")
        print(f"  [{severity}] {tid} — doc action: {action}")

    print(f"[CE] Post-mortem complete: {len(results)} report(s) written.")
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_default_llm() -> Callable[[str], str]:
    """Load the default LLM from models_config.yaml."""
    from core_orchestrator.model_router import ModelRouter

    config_path = Path(__file__).parent / "models_config.yaml"
    router = ModelRouter(config_path)
    return router.as_llm()


def _load_default_tool_llm():
    """Load the default Tool Use LLM from models_config.yaml."""
    from core_orchestrator.model_router import ModelRouter

    config_path = Path(__file__).parent / "models_config.yaml"
    router = ModelRouter(config_path)
    return router.as_tool_llm()


def _make_tool_llm_from_text_llm(text_llm: Callable[[str], str]):
    """Wrap a text-based LLM callable into a tool_llm callable.

    This is a compatibility shim for tests that provide a simple text LLM.
    It calls the text LLM and parses the response using a lightweight regex
    fallback to extract file blocks from the text output.
    """
    import re
    from core_orchestrator.llm_connector import ToolCall

    _FILE_BLOCK_RE = re.compile(
        r"={2,4}\s*FILE:\s*(.+?)\s*={2,4}\s*\n(.*?)(?=\n={2,4}\s*(?:FILE:|END)\s*={0,4}|$)",
        re.DOTALL,
    )

    def _tool_llm(system: str, user_prompt: str, tools):
        # Combine system + user into a single text prompt for the text LLM
        combined = f"{system}\n\n{user_prompt}"
        response = text_llm(combined)
        # Parse ===FILE: path=== blocks from text response
        matches = _FILE_BLOCK_RE.findall(response)
        calls = []
        for path, content in matches:
            clean_path = path.strip().strip("`'\"")
            if clean_path:
                calls.append(ToolCall(
                    name="write_file",
                    arguments={"filepath": clean_path, "content": content.rstrip()},
                ))
        return calls

    return _tool_llm


def run_update_mode(
    *,
    workspace: WorkspaceManager,
    workspace_id: str,
    requirement: str,
    llm: Optional[Callable[[str], str]] = None,
    tool_llm=None,
    bus=None,
) -> Dict:
    """Run Update Mode: generate incremental tasks and execute them.

    1. CEO reads existing deliverables and generates update tasks
    2. Delegate writes new task files (append-only)
    3. ResilienceManager runs Architect on new tasks only

    Returns the ResilienceManager.status() dict.
    """
    sanitizer = default_pipeline()
    _llm = llm or _load_default_llm()

    # Phase 1: CEO plans update
    gateway = LLMGateway(sanitizer=sanitizer, llm=_llm)
    ceo = CEOAgent(gateway=gateway, workspace=workspace, workspace_id=workspace_id)

    # Load workspace lessons for context injection
    solution_store = SolutionStore(workspace, workspace_id)
    solutions_ctx  = solution_store.format_as_context()
    if solutions_ctx:
        print(f"[Solutions] Loaded {solution_store.count()} lesson(s) from workspace.\n")

    print(f"\n[Update] Analyzing existing codebase and planning changes...")
    plan = ceo.plan_update(requirement, solutions_context=solutions_ctx)

    tasks = plan.get("tasks", [])
    if not tasks:
        print("[Update] CEO generated 0 tasks. Nothing to do.")
        return {"completed": [], "escalated": [], "token_usage": 0}

    print(f"[Update] Generated {len(tasks)} update task(s):")
    for t in tasks:
        files = t.get("files_to_modify", [])
        files_str = f" (files: {', '.join(files)})" if files else ""
        print(f"  - [{t['priority']}] {t['id']}: {t['title']}{files_str}")

    # Phase 2: Delegate (append-only)
    delegated_files = ceo.delegate()
    print(f"[Update] Delegated {len(delegated_files)} task file(s).")

    # Phase 3: Execute only the new tasks
    _tool_llm = tool_llm or _make_tool_llm_from_text_llm(_llm)
    exec_cfg = _load_execution_config()
    qa_gateway = LLMGateway(sanitizer=sanitizer, llm=_llm)

    km = KnowledgeManager(workspace=workspace, workspace_id=workspace_id)
    knowledge_ctx = km.load_knowledge()

    rm = ResilienceManager(
        workspace=workspace,
        workspace_id=workspace_id,
        tool_llm=_tool_llm,
        qa_gateway=qa_gateway,
        max_retries=exec_cfg.get("max_retries", 3),
        token_budget=exec_cfg.get("token_budget", 100_000),
        token_threshold=exec_cfg.get("token_threshold", 0.8),
        eval_timeout=exec_cfg.get("eval_timeout", 30),
        knowledge_manager=km,
        knowledge_context=knowledge_ctx,
        solutions_context=solutions_ctx,
        bus=bus,
    )

    # Only run the newly generated tasks (not all tasks)
    new_task_ids = [t["id"] for t in tasks]
    if bus:
        bus.emit("pipeline.update_start", task_count=len(new_task_ids))

    print(f"\n[Execution] Running Architect + Evaluator + QA on {len(new_task_ids)} update task(s)...")
    results = [rm.run_task_loop(tid) for tid in new_task_ids]

    for r in results:
        tag = "PASS" if r["verdict"] == "pass" else "ESCALATED"
        print(f"  [{tag}] {r['task_id']} (attempts: {r['attempts']}) -> {r['path']}")

    status = rm.status()
    passed = len(status["completed"])
    escalated = len(status["escalated"])
    print(f"[Update] Done: {passed} passed, {escalated} escalated, "
          f"tokens used: {status['token_usage']}")

    if bus:
        bus.emit("pipeline.update_complete", passed=passed, escalated=escalated)

    return status


def _print_summary(status: Dict, ws_id: str) -> None:
    print("\n" + "=" * 60)
    print("  Pipeline Complete")
    print("=" * 60)
    passed = len(status.get("completed", []))
    escalated = len(status.get("escalated", []))
    print(f"  Tasks passed:    {passed}")
    print(f"  Tasks escalated: {escalated}")
    print(f"  Token usage:     {status.get('token_usage', 0)}")
    print(f"  Workspace:       workspaces/{ws_id}/")
    print("=" * 60)


# ---------------------------------------------------------------------------
# main() — wire everything together with checkpoint resume
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AegisHarness — Multi-agent orchestration CLI",
    )
    parser.add_argument(
        "--workspace", "-w",
        default=DEFAULT_WORKSPACE_ID,
        help=f"Workspace ID (default: {DEFAULT_WORKSPACE_ID})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Discard checkpoint and start fresh",
    )
    parser.add_argument(
        "--update", "-u",
        type=str,
        default=None,
        metavar="DESCRIPTION",
        help="Update Mode: provide a change/fix description to modify existing deliverables",
    )
    args = parser.parse_args()

    ws_id = args.workspace

    print("=" * 60)
    print("  AegisHarness — Multi-Agent Orchestrator")
    print("=" * 60)
    print(f"Workspace: {ws_id}\n")

    # Bootstrap workspace
    root = WORKSPACE_ROOT
    ws = WorkspaceManager(root, isolated=True)
    if not ws.exists(ws_id):
        ws.create(ws_id)

    # Create event bus for real-time observability
    bus = bus_from_workspace(ws, ws_id)
    bus.emit("pipeline.start", workspace=ws_id)

    # ------------------------------------------------------------------
    # Update Mode — short-circuit the normal pipeline
    # ------------------------------------------------------------------
    if args.update:
        print(f"[Update Mode] Requirement: {args.update}\n")
        status = run_update_mode(
            workspace=ws,
            workspace_id=ws_id,
            requirement=args.update,
            bus=bus,
        )
        _print_summary(status, ws_id)
        bus.emit("pipeline.complete", workspace=ws_id)
        return

    # Load or reset checkpoint
    checkpoint = None
    if args.reset:
        if ws.exists(ws_id, CHECKPOINT_FILE):
            ws.delete(ws_id, CHECKPOINT_FILE)
        print("[Checkpoint] Reset — starting fresh.\n")
    else:
        checkpoint = load_checkpoint(ws, ws_id)

    if checkpoint and _stage_done(checkpoint, "postmortem"):
        print("[Checkpoint] Pipeline already complete.")
        print(f"  Requirement: {checkpoint.get('requirement', '?')}")
        _print_summary(checkpoint.get("execution_status", {}), ws_id)
        print("\nRe-run with --reset to start over.")
        return

    if checkpoint:
        stage = checkpoint["stage"]
        req = checkpoint.get("requirement", "")
        print(f"[Checkpoint] Resuming from stage: {stage}")
        print(f"  Requirement: {req}\n")

    # ------------------------------------------------------------------
    # Phase 1a: CEO interview + plan
    # ------------------------------------------------------------------
    requirement = checkpoint.get("requirement", "") if checkpoint else ""

    if not _stage_done(checkpoint, "interviewed"):
        ceo = build_pipeline(workspace_root=root, workspace_id=ws_id)

        print("Enter your requirement (what do you want to build?):")
        requirement = input("> ")

        if not requirement.strip():
            print("Error: requirement cannot be empty.")
            sys.exit(1)

        # Load workspace solutions for CEO planning (Compound Learning)
        solution_store = SolutionStore(ws, ws_id)
        solutions_ctx  = solution_store.format_as_context()
        if solutions_ctx:
            print(f"[Solutions] Loaded {solution_store.count()} lesson(s) from workspace.\n")

        run_interview_loop(ceo, requirement, solutions_context=solutions_ctx)
        save_checkpoint(ws, ws_id, stage="interviewed", requirement=requirement)
        print("[Checkpoint] Saved: interviewed\n")
    else:
        print("[Skip] Interview + plan already done.")
        solution_store = SolutionStore(ws, ws_id)
        solutions_ctx  = solution_store.format_as_context()

    # ------------------------------------------------------------------
    # Phase 1b: Delegate tasks
    # ------------------------------------------------------------------
    if not _stage_done(checkpoint, "delegated"):
        # If we just ran the interview, ceo is available; otherwise rebuild
        if "ceo" not in dir():
            # Interview was done in a previous run; CEO state is lost,
            # but plan.md and tasks are already on disk — we need to
            # delegate only if tasks/ doesn't exist yet.
            # Since interview was done but delegate wasn't, we need a CEO.
            # Re-build and drive it through the saved state.
            pass  # We rely on the fact that `ceo` was defined above in Phase 1a

        print("Delegating tasks to workspace...")
        files = ceo.delegate()
        print(f"[CEO] Delegated {len(files)} task file(s):")
        for f in files:
            print(f"  -> {f}")
        save_checkpoint(ws, ws_id, stage="delegated", requirement=requirement)
        print("[Checkpoint] Saved: delegated\n")
    else:
        print("[Skip] Delegation already done.")

    # ------------------------------------------------------------------
    # Phase 2: Architect + QA via ResilienceManager
    # ------------------------------------------------------------------
    if not _stage_done(checkpoint, "executed"):
        status = run_execution(
            workspace=ws,
            workspace_id=ws_id,
            bus=bus,
            solutions_context=solutions_ctx,
        )
        save_checkpoint(ws, ws_id, stage="executed",
                        requirement=requirement, execution_status=status)
        print("[Checkpoint] Saved: executed\n")
    else:
        print("[Skip] Execution already done.")
        status = checkpoint.get("execution_status", {})

    # ------------------------------------------------------------------
    # Phase 3a: Reflection Agent — Compound Learning (always runs)
    # ------------------------------------------------------------------
    run_reflection(
        workspace=ws,
        workspace_id=ws_id,
        requirement=requirement,
        bus=bus,
    )

    # ------------------------------------------------------------------
    # Phase 3b: CE Orchestrator post-mortem
    # ------------------------------------------------------------------
    if not _stage_done(checkpoint, "postmortem"):
        run_postmortem(workspace=ws, workspace_id=ws_id)
        save_checkpoint(ws, ws_id, stage="postmortem",
                        requirement=requirement, execution_status=status)
        print("[Checkpoint] Saved: postmortem\n")
    else:
        print("[Skip] Post-mortem already done.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    _print_summary(status, ws_id)
    bus.emit("pipeline.complete", workspace=ws_id)


if __name__ == "__main__":
    main()
