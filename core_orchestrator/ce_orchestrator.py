"""CE (Compound Experience) orchestrator — post-mortem analysis with 5 sub-agents.

Runs five independent analyses on a completed task, merges results into
a structured post-mortem document, and saves it to the workspace.
"""

from pathlib import Path
from typing import Dict, List, Optional

from .json_parser import parse_llm_json
from .llm_gateway import LLMGateway
from .workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Sub-agent prompts
# ---------------------------------------------------------------------------

_CONTEXT_PROMPT = """\
You are a context analyst. Given the following task history, extract:
1. The type of problem encountered
2. Which components/modules were involved
3. The severity level (low/medium/high/critical)

Task History:
{context}

Respond in strict JSON (no markdown fences):
{{"problem_type": "...", "components": ["..."], "severity": "..."}}
"""

_SOLUTION_PROMPT = """\
You are a solution analyst. Given the following task history, extract:
1. What approaches were tried and failed (with brief reasons)
2. The root cause of the problem
3. The final working solution

Task History:
{context}

Respond in strict JSON (no markdown fences):
{{"failed_attempts": ["attempt: reason", ...], "root_cause": "...", "final_solution": "..."}}
"""

_DOC_SEARCH_PROMPT = """\
You are a documentation dedup specialist. Decide whether this experience \
duplicates an existing document or requires a new one.

Task History:
{context}

Existing documents in knowledge base:
{existing_docs}

Respond in strict JSON (no markdown fences):
{{"existing_doc": "filename.md" or null, "action": "update" or "create"}}
"""

_PREVENTION_PROMPT = """\
You are a prevention strategist. Based on this post-mortem, propose \
concrete strategies to prevent similar issues in the future.

Task History:
{context}

Respond in strict JSON (no markdown fences):
{{"strategies": ["strategy 1", "strategy 2", ...]}}
"""

_CLASSIFY_PROMPT = """\
You are a documentation classifier. Assign tags and a category path \
to this experience for future retrieval.

Task History:
{context}

Respond in strict JSON (no markdown fences):
{{"tags": ["tag1", "tag2", ...], "category": "domain/subdomain"}}
"""


# ---------------------------------------------------------------------------
# Sub-agent functions (each: gateway + context → dict)
# ---------------------------------------------------------------------------

def analyze_context(gateway: LLMGateway, context: str) -> Dict:
    """Sub-agent 1: Extract problem type, components, severity."""
    prompt = _CONTEXT_PROMPT.format(context=context)
    result = gateway.send(prompt)
    return parse_llm_json(result["llm_response"])


def extract_solution(gateway: LLMGateway, context: str) -> Dict:
    """Sub-agent 2: Extract failed attempts, root cause, final solution."""
    prompt = _SOLUTION_PROMPT.format(context=context)
    result = gateway.send(prompt)
    return parse_llm_json(result["llm_response"])


def search_docs(gateway: LLMGateway, context: str, existing_docs: List[str]) -> Dict:
    """Sub-agent 3: Check knowledge base for duplicates."""
    docs_str = "\n".join(f"- {d}" for d in existing_docs) if existing_docs else "- (none)"
    prompt = _DOC_SEARCH_PROMPT.format(context=context, existing_docs=docs_str)
    result = gateway.send(prompt)
    return parse_llm_json(result["llm_response"])


def plan_prevention(gateway: LLMGateway, context: str) -> Dict:
    """Sub-agent 4: Propose prevention strategies."""
    prompt = _PREVENTION_PROMPT.format(context=context)
    result = gateway.send(prompt)
    return parse_llm_json(result["llm_response"])


def classify(gateway: LLMGateway, context: str) -> Dict:
    """Sub-agent 5: Assign tags and category."""
    prompt = _CLASSIFY_PROMPT.format(context=context)
    result = gateway.send(prompt)
    return parse_llm_json(result["llm_response"])


# ---------------------------------------------------------------------------
# CE Orchestrator
# ---------------------------------------------------------------------------

class CEOrchestrator:
    """Runs 5 sub-agents for post-mortem analysis and writes structured docs."""

    def __init__(
        self,
        gateway: LLMGateway,
        workspace: WorkspaceManager,
        workspace_id: str,
        knowledge_base_path: Optional[str] = None,
    ):
        self._gateway = gateway
        self._workspace = workspace
        self._ws_id = workspace_id
        self._kb_path = Path(knowledge_base_path) if knowledge_base_path else None

    def _gather_context(self, task_id: str) -> str:
        """Collect all relevant files for a task into a single context string."""
        sections = []

        task_file = f"tasks/{task_id}.md"
        if self._workspace.exists(self._ws_id, task_file):
            sections.append(f"## Task\n{self._workspace.read(self._ws_id, task_file)}")

        artifact_file = f"artifacts/{task_id}_solution.md"
        if self._workspace.exists(self._ws_id, artifact_file):
            sections.append(f"## Solution\n{self._workspace.read(self._ws_id, artifact_file)}")

        feedback_file = f"feedback/{task_id}_feedback.md"
        if self._workspace.exists(self._ws_id, feedback_file):
            sections.append(f"## QA Feedback\n{self._workspace.read(self._ws_id, feedback_file)}")

        escalation_file = f"escalations/{task_id}_escalation.md"
        if self._workspace.exists(self._ws_id, escalation_file):
            sections.append(f"## Escalation\n{self._workspace.read(self._ws_id, escalation_file)}")

        return "\n\n".join(sections)

    def _list_kb_docs(self) -> List[str]:
        """List existing .md files in the knowledge base directory."""
        if not self._kb_path or not self._kb_path.is_dir():
            return []
        return sorted(p.name for p in self._kb_path.glob("*.md"))

    def _format_postmortem(self, task_id: str, merged: Dict) -> str:
        """Render merged results as a structured Markdown document."""
        ctx = merged["context_analysis"]
        sol = merged["solution_extraction"]
        prev = merged["prevention_plan"]
        clf = merged["classification"]
        doc = merged["doc_search"]

        tags_str = ", ".join(f"`{t}`" for t in clf.get("tags", []))
        strategies = "\n".join(
            f"{i}. {s}" for i, s in enumerate(prev.get("strategies", []), 1)
        )
        failed = "\n".join(
            f"- {a}" for a in sol.get("failed_attempts", [])
        )

        return (
            f"# Post-Mortem: {task_id}\n\n"
            f"**Tags:** {tags_str}\n"
            f"**Category:** {clf.get('category', 'uncategorized')}\n"
            f"**Severity:** {ctx.get('severity', 'unknown')}\n"
            f"**Doc Action:** {doc.get('action', 'create')}\n\n"
            f"## Problem Type\n{ctx.get('problem_type', 'N/A')}\n\n"
            f"## Components\n{', '.join(ctx.get('components', []))}\n\n"
            f"## Failed Attempts\n{failed or 'None'}\n\n"
            f"## Root Cause\n{sol.get('root_cause', 'N/A')}\n\n"
            f"## Final Solution\n{sol.get('final_solution', 'N/A')}\n\n"
            f"## Prevention Strategies\n{strategies or 'None'}\n"
        )

    def analyze(self, task_id: str) -> Dict:
        """Run all 5 sub-agents and write a post-mortem document."""
        context = self._gather_context(task_id)
        kb_docs = self._list_kb_docs()

        # Run 5 sub-agents (independent, could be parallelized)
        ctx_result = analyze_context(self._gateway, context)
        sol_result = extract_solution(self._gateway, context)
        doc_result = search_docs(self._gateway, context, kb_docs)
        prev_result = plan_prevention(self._gateway, context)
        clf_result = classify(self._gateway, context)

        merged = {
            "task_id": task_id,
            "context_analysis": ctx_result,
            "solution_extraction": sol_result,
            "doc_search": doc_result,
            "prevention_plan": prev_result,
            "classification": clf_result,
        }

        # Write post-mortem
        postmortem = self._format_postmortem(task_id, merged)
        self._workspace.write(
            self._ws_id, f"docs/solutions/{task_id}_postmortem.md", postmortem
        )

        return merged

    def analyze_all(self) -> List[Dict]:
        """Run post-mortem for all tasks that have artifacts."""
        all_files = self._workspace.list_files(self._ws_id)
        task_ids = sorted(
            f.removeprefix("tasks/").removesuffix(".md")
            for f in all_files
            if f.startswith("tasks/") and f.endswith(".md")
        )
        reviewable = [
            tid for tid in task_ids
            if self._workspace.exists(self._ws_id, f"artifacts/{tid}_solution.md")
        ]
        return [self.analyze(tid) for tid in reviewable]
