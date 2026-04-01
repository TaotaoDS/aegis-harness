# Translation Gateway & CE Orchestrator

## 1. Translation Gateway — Multilingual Support with English-Only Internals

### Problem
When users communicate in non-English languages (e.g., Chinese), passing raw non-English text through the entire agent pipeline wastes tokens (CJK characters have poor token efficiency) and degrades model reasoning quality (LLMs reason more reliably in English).

### Design Decision
Introduce a **translation gateway** pattern at the CEO agent boundary:

- **User-facing**: CEO interview prompts instruct the LLM to respond in the **user's native language** (detected from the original requirement).
- **Internal pipeline**: All downstream artifacts are **strictly English-only**, enforced via an `IRON RULE` directive injected into every agent's system prompt.

### Implementation

**CEO Agent** (`ceo_agent.py`):
- `_INTERVIEW_SYSTEM`: Added instruction to respond in user's language for user-facing communication.
- `_PLAN_SYSTEM`: Added `IRON RULE: All output MUST be in English`.

**Architect Agent** (`architect_agent.py`):
- `_SOLVE_SYSTEM`: Added `IRON RULE: All output MUST be in English`.

**QA Agent** (`qa_agent.py`):
- `_REVIEW_SYSTEM`: Added `IRON RULE: All output MUST be in English`.

**CE Orchestrator** (`ce_orchestrator.py`):
- Prompts are already English-only by design (no changes needed).

### Affected Artifacts
All internal workspace artifacts are English-only:
- `plan.md`, `tasks/*.md`, `artifacts/*.md`
- `feedback/*.md`, `approved/*.md`
- `docs/solutions/*.md`, `escalations/*.md`

### Trade-offs
- **Pro**: 30-50% token savings on CJK input; more consistent model reasoning.
- **Pro**: Zero runtime overhead — enforcement is purely prompt-level.
- **Con**: Translation quality depends on the LLM's multilingual capability.

---

## 2. CE Orchestrator — Post-Mortem Analysis Engine

### Problem
After the Architect-QA-Resilience loop completes a task, valuable lessons (root cause, failed approaches, prevention strategies) are lost. The system needs a structured knowledge capture mechanism.

### Design Decision
Implement a **CE (Compound Experience) Orchestrator** with 5 independent sub-agent analysis functions, following the same stateless executor pattern as the Architect.

### Architecture

```
CEOrchestrator.analyze(task_id)
    |
    +-- _gather_context(task_id)     # Collect task/artifact/feedback/escalation
    |
    +-- 5 sub-agents (independent, parallelizable):
    |   |-- analyze_context()        # Problem type, components, severity
    |   |-- extract_solution()       # Failed attempts, root cause, final solution
    |   |-- search_docs()            # Knowledge base dedup check
    |   |-- plan_prevention()        # Future prevention strategies
    |   +-- classify()               # Tags and category for retrieval
    |
    +-- _format_postmortem()         # Merge into structured Markdown
    +-- write to docs/solutions/{task_id}_postmortem.md
```

### Sub-Agent Functions

Each sub-agent is a pure function: `(gateway, context) -> Dict`

| Function | Input | Output |
|----------|-------|--------|
| `analyze_context` | Task history | `{problem_type, components[], severity}` |
| `extract_solution` | Task history | `{failed_attempts[], root_cause, final_solution}` |
| `search_docs` | Task history + existing docs | `{existing_doc, action: "create"/"update"}` |
| `plan_prevention` | Task history | `{strategies[]}` |
| `classify` | Task history | `{tags[], category}` |

### Knowledge Base Dedup
- `_list_kb_docs()` scans an optional `knowledge_base_path` for existing `.md` files.
- `search_docs` sub-agent decides whether to `create` a new doc or `update` an existing one.
- Prevents duplicate post-mortems for recurring issue patterns.

### Context Gathering
`_gather_context()` assembles a unified context string from up to 4 workspace files:
- `tasks/{task_id}.md` — original task
- `artifacts/{task_id}_solution.md` — architect's solution
- `feedback/{task_id}_feedback.md` — QA feedback (optional)
- `escalations/{task_id}_escalation.md` — resilience escalation (optional)

### Post-Mortem Output Format
```markdown
# Post-Mortem: {task_id}
**Tags:** `tag1`, `tag2`
**Category:** domain/subdomain
**Severity:** high
**Doc Action:** create

## Problem Type / Components / Failed Attempts / Root Cause / Final Solution / Prevention Strategies
```

### API

```python
ce = CEOrchestrator(gateway, workspace, workspace_id, knowledge_base_path=None)
result = ce.analyze("task_1")        # Single task post-mortem
results = ce.analyze_all()           # All tasks with artifacts
```

### Test Coverage
- 16 tests for translation gateway (across all 5 agents)
- 18 tests for CE orchestrator (5 sub-agent + pipeline + analyze_all + dedup)
- Total: 34 new tests, 209 total suite
