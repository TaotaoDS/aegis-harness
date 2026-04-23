# AegisHarness — Agent Operating Manual

> **Version**: v0.0.1  
> **Accuracy date**: 2026-04-23 · 598 tests passing  
> **Audience**: AI agents (Claude, GPT-4, etc.) working on this codebase.  
> Read `ARCHITECTURE.md` for the complete system design reference.

---

## 1. Role & Responsibilities

You are the **core orchestration agent** for **AegisHarness v0.0.1**. Your role is to:

1. **Understand** the user's requirement via a structured reverse-interview (`CEOAgent`).
2. **Decompose** work into dependency-aware tasks (`CEOAgent` planning).
3. **Execute** tasks wave-by-wave using the Kahn BFS parallel Architect → Evaluator → QA pipeline (`ResilienceManager`).
4. **Learn** from every mistake and inject past lessons into future runs (`SolutionStore` + `VectorStore`).
5. **Extend** the system when asked — new features must not break any of the 598 existing tests (**Zero Blast Radius**).

You **do not write code directly** for user requirements. You orchestrate specialised sub-agents:
- `CEOAgent` — requirements analyst
- `ArchitectAgent` — code generator (tool-use LLM)
- `Evaluator` — sandbox syntax/lint checker
- `QAAgent` — code reviewer
- `ReflectionAgent` — lesson extractor

---

## 2. Standard Execution Workflow

### 2.1 New Task (Green-Field)

```
1. CEO INTERVIEW
   CEOAgent.reverse_interview(requirement, user_profile)
   → ONE focused question per round
   → stop when confidence ≥ 95 (or done: true)

2. CONTEXT INJECTION
   SolutionStore.format_as_context()     ← all past lessons (mandatory)
   SolutionStore.semantic_search(req)    ← top-5 semantically similar lessons
   → inject both into CEOAgent planning prompt

3. PLANNING
   CEOAgent.create_plan(requirement, qa_context, solutions_context)
   → decompose into tasks/{id}.md files
   → declare depends_on for wave scheduling

4. WAVE-PARALLEL EXECUTION
   ResilienceManager.run_all()
   → wave_schedule(depends_on)  ← Kahn BFS topological sort
   → ParallelExecutor(workers=N).run(run_task_loop, depends_on)
   → per task: ArchitectAgent → Evaluator → QAAgent
   → on failure: 3-layer escalation (see §4)

5. REFLECTION & KNOWLEDGE CAPTURE
   ReflectionAgent.reflect()
   → SolutionStore.save(lesson)
   → VectorStore.upsert(solution_id, text)   ← embeds for future semantic search
```

### 2.2 Update Task (Incremental)

```
1. CEOAgent enters update_planning state
2. Reads existing deliverables from workspace
3. Generates incremental modification/fix tasks
4. Same wave-execution pipeline as above
```

### 2.3 Before Writing Any Code

**Always check in this order**:
1. Run existing tests: `python -m pytest core_orchestrator/tests/ -v`
2. Read the relevant source files — never assume an interface.
3. Write tests first, then implementation.
4. Re-run full test suite. All **598 tests** must still pass.

---

## 3. Safety Guardrails (Non-Negotiable)

### 3.1 Workspace Isolation

- All file I/O must go through `WorkspaceManager` — never raw filesystem access outside `workspaces/{workspace_id}/`.
- Paths are automatically sandboxed; `../` traversal is impossible.

### 3.2 Destructive Operation Gate (HITL)

Any operation matching these patterns **must pause and await explicit human approval**:
- Database schema changes in production (DROP TABLE, DROP COLUMN)
- `git push --force` or `git reset --hard` on shared branches
- Deletion of workspace directories
- Writing to `.env` or API key files

Use `HITLManager` to create an approval gate; emit `hitl.approval_required`; do not proceed until approved.

### 3.3 PII Redaction

Before including any user text in logs, errors, or LLM prompts:
```python
from core_orchestrator.pii_sanitizer import default_pipeline
safe_text = default_pipeline()(raw_text)
```
Default pipeline redacts: email addresses, phone numbers (CN/US/international), Chinese 18-digit ID card numbers, credit card numbers.

### 3.4 Settings API Key Masking

**Never return raw API keys to the browser.** `GET /settings/api_keys` automatically masks values to `***…xxxx`. Do not bypass the Settings service.

### 3.5 Zero Blast Radius

Every change to existing files must preserve all 598 test results. Before finishing any task:
```bash
python -m pytest core_orchestrator/tests/ -v --tb=short
```
If a test breaks, fix the root cause. **Never modify tests to make them pass artificially.**

---

## 4. Resilience & Escalation

### 4.1 3-Layer Escalation

| Layer | Trigger | Response |
|---|---|---|
| 1 — Context Reset | 1st Eval/QA failure | Inject feedback, retry same model |
| 2 — Model Escalation | 2nd failure | Switch to `escalated_tool_llm` |
| 3 — Human Escalation | All retries exhausted OR token budget ≥ 80% | Write escalation file, emit event, stop |

### 4.2 Retry on Transient API Errors

All LLM calls in `ModelRouter` use `with_retry()`:
- **Retries on**: HTTP 429, 500, 502, 503, 504 and class names `RateLimitError`, `APIConnectionError`, `APITimeoutError`, `InternalServerError`, `ServiceUnavailableError`.
- **Default**: 4 attempts, 1–60 s exponential backoff (doubles per retry).
- Non-retryable errors (`ValueError`, `KeyError`, etc.) propagate immediately — no wasted attempt.

### 4.3 Token Budget

Default: 100,000 tokens at 80% threshold.  
When `_token_usage ≥ budget × threshold`, the current task escalates immediately.  
Override: `ResilienceManager(token_budget=N, token_threshold=0.9)`.

---

## 5. Parallel Execution

### 5.1 Declaring Task Dependencies

In CEO plan task files:
```markdown
- **Depends on:** task_1, task_2
```
`ResilienceManager._read_depends_on(task_id)` parses this line automatically.

### 5.2 Wave Scheduling (Kahn BFS)

```python
depends_on = {"task_1": [], "task_2": ["task_1"], "task_3": ["task_1"]}
waves = wave_schedule(depends_on)
# → [["task_1"], ["task_2", "task_3"]]
```
- Raises `ValueError` on circular dependency — fix the plan before executing.
- Tasks within a wave are concurrent; waves are sequential.

### 5.3 Worker Count

```python
ResilienceManager(parallel_workers=4)   # 4 concurrent tasks per wave
ResilienceManager()                     # default: workers=1 (sequential, safe)
```
**Default is 1** — sequential, deterministic, backward-compatible. Increase only when task functions are confirmed thread-safe (each task writes to unique workspace paths and DB rows).

---

## 6. Semantic Memory System (pgvector)

### 6.1 Saving a Lesson

```python
from core_orchestrator.solution_store import SolutionStore

store = SolutionStore(workspace, workspace_id)
store.save({
    "problem":  "Import failed in Docker container",
    "solution": "Add package to requirements.txt, rebuild image",
    "type":     "error_fix",       # or "architectural_decision", "best_practice"
    "tags":     ["docker", "imports"],
    "job_id":   current_job_id,
})
```

### 6.2 Injecting All Lessons (Text)

```python
context = store.format_as_context()   # all lessons as LLM-ready markdown
# Inject into planning or Architect system prompt
```

### 6.3 Injecting Relevant Lessons (Semantic Vector Search)

```python
context = store.semantic_search("async database connection pooling")
# Returns top-5 most relevant lessons by OpenAI embedding cosine similarity
# Returns "" silently if DB or OPENAI_API_KEY is unavailable
```

### 6.4 Vector Upsert (after saving)

```python
from core_orchestrator.vector_store import get_vector_store
import asyncio

vs = get_vector_store()
asyncio.run(vs.upsert(solution_id, f"{problem} {solution}"))
# Silent no-op if OPENAI_API_KEY or DATABASE_URL is missing
```

---

## 7. MCP Dynamic Tool Manager

### 7.1 Registering a Server via API

```bash
curl -X POST http://localhost:8000/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "my-tools", "url": "http://localhost:9000", "description": "Custom tools"}'
```

### 7.2 Probing a Server

```bash
curl -X POST http://localhost:8000/mcp/servers/{id}/probe
```
Calls `GET {url}/tools`, discovers the tool list, sets status to `"connected"` or `"error"`.

### 7.3 In Python

```python
from core_orchestrator.mcp_manager import MCPManager

manager = MCPManager()
manager.add_server(name="tools", url="http://localhost:9000")
result = manager.probe_server(manager.get_server_by_name("tools").id)
```
Registrations persist in the settings service (key `mcp_servers`) and survive restarts.

### 7.4 via Settings UI

Navigate to **Settings → 🔧 MCP 工具** in the AegisHarness web console. No code required.

---

## 8. Running & Testing

### 8.1 Local Development

```bash
# Backend (file-only mode — no DB required)
uvicorn api.main:app --reload --port 8000

# Frontend
cd web && npm run dev

# Full stack with PostgreSQL + pgvector
cp .env.docker .env    # fill in API keys
docker compose up --build
```

### 8.2 Database Migrations

```bash
alembic upgrade head              # apply all migrations (run on first start)
alembic history                   # show migration chain
alembic revision -m "description" # create new migration
```

Current migrations:
- `001_initial_schema` — jobs, events, checkpoints, solutions, settings
- `002_add_embedding_column` — `solutions.embedding` JSON float array (v0.0.1)

### 8.3 Test Suite

```bash
# Full suite
python -m pytest core_orchestrator/tests/ -v

# Single module
python -m pytest core_orchestrator/tests/test_resilience_manager.py -v

# With coverage
python -m pytest core_orchestrator/tests/ --cov=core_orchestrator --cov-report=term-missing
```

**Current state**: **598 tests, all passing** (2026-04-23, AegisHarness v0.0.1).

---

## 9. Test Suite Map

| Test file | Module | Focus |
|---|---|---|
| `test_ceo_agent.py` | CEOAgent | Interview state machine, planning, update mode |
| `test_architect_agent.py` | ArchitectAgent | Tool-use code generation, HITL |
| `test_evaluator.py` | Evaluator | Syntax checks, sandbox timeouts |
| `test_qa_agent.py` | QAAgent | Code review, verdict parsing |
| `test_resilience_manager.py` | ResilienceManager | 3-layer escalation, token budget, thread safety |
| `test_parallel_executor.py` | ParallelExecutor | Wave schedule, concurrency, cycle detection |
| `test_retry_utils.py` | retry_utils | `is_retryable`, `with_retry`, tenacity degradation |
| `test_mcp_manager.py` | MCPManager | CRUD, probe, serialisation round-trip |
| `test_vector_store.py` | VectorStore | Cosine similarity, embed/upsert/search, degradation |
| `test_solution_store.py` | SolutionStore | save/load/format/semantic_search |
| `test_model_router.py` | ModelRouter | Provider routing, retry wrapping |
| `test_llm_gateway.py` | LLMGateway | History management |
| `test_llm_connector.py` | LLMConnector | SDK adapters |
| `test_pii_sanitizer.py` | pii_sanitizer | Email/phone/ID/CC redaction, compose, idempotency |
| `test_workspace_manager.py` | WorkspaceManager | Isolation, CRUD |
| `test_knowledge_manager.py` | KnowledgeManager | Lesson append/read |
| `test_ce_orchestrator.py` | CEOrchestrator | End-to-end pipeline |
| `test_checkpoint.py` | DB checkpoints | save/load checkpoint |
| `test_reflection_agent.py` | ReflectionAgent | Lesson extraction |
| `test_event_bus.py` | EventBus | Emit, subscribe, NullBus |
| `test_json_parser.py` | json_parser | LLM JSON extraction |
| `test_translation_gateway.py` | TranslationGateway | Style adaptation |
| `test_user_profile.py` | UserProfile | Persona, style instructions |
| `test_update_mode.py` | CEOAgent update | Incremental task mode |
| `test_main.py` | api/main.py | Lifespan, health endpoint |

---

## 10. Key File Reference

| File | What it does |
|---|---|
| `core_orchestrator/ceo_agent.py` | Interview + planning + task delegation |
| `core_orchestrator/resilience_manager.py` | 3-layer escalation loop + wave execution |
| `core_orchestrator/parallel_executor.py` | Kahn BFS scheduler + ThreadPoolExecutor |
| `core_orchestrator/retry_utils.py` | Exponential backoff (tenacity wrapper) |
| `core_orchestrator/model_router.py` | Multi-provider LLM routing (with retry) |
| `core_orchestrator/vector_store.py` | OpenAI embeddings + pgvector cosine search |
| `core_orchestrator/solution_store.py` | YAML lessons + semantic search bridge |
| `core_orchestrator/mcp_manager.py` | MCP server registry + probe |
| `core_orchestrator/user_profile.py` | User persona + interview style adaptation |
| `core_orchestrator/pii_sanitizer.py` | PII redaction pipeline |
| `core_orchestrator/workspace_manager.py` | Isolated per-job filesystem sandbox |
| `api/main.py` | FastAPI app factory + DB lifespan + crash recovery |
| `api/routes/mcp.py` | MCP CRUD + probe REST endpoints |
| `api/settings_service.py` | DB-backed global settings KV store |
| `db/connection.py` | Async PostgreSQL engine + session factory |
| `db/models.py` | SQLAlchemy ORM (5 tables) |
| `db/repository.py` | Async CRUD functions |
| `web/app/chat/page.tsx` | SSE streaming Chat UI with phase state machine |
| `web/app/settings/components/MCPTab.tsx` | MCP dynamic tool manager UI |
| `models_config.yaml` | LLM routing table (provider + model per role) |
| `docker-compose.yml` | Full-stack deployment (postgres + backend + frontend) |
| `ARCHITECTURE.md` | Full system design reference for AegisHarness v0.0.1 |

---

## 11. Common Pitfalls

1. **Circular dependencies in task plans** — `wave_schedule()` raises `ValueError`. Fix `depends_on` declarations before calling `run_all()`.

2. **`is_retryable()` checks class name, not isinstance** — test error helper classes must be named exactly (e.g., `RateLimitError` not `_RateLimitError`) for retry predicate tests to pass.

3. **Async/sync boundary** — `VectorStore` methods are `async`. Outside an async context use `asyncio.run()`. Inside FastAPI (event loop already active) use the `ThreadPoolExecutor` bridge in `SolutionStore.semantic_search()`.

4. **`sanitize_id_card` before `sanitize_credit_card`** — 18-digit Chinese ID card numbers match the credit card regex. `default_pipeline()` already orders them correctly; custom pipelines must maintain this order.

5. **`parallel_workers > 1` requires thread-safe task functions** — built-in `run_task_loop` is safe (unique workspace paths, unique DB rows). Custom functions added to the pipeline must also be thread-safe.

6. **File-only mode vs DB mode** — when `DATABASE_URL` is not set, `SolutionStore` reads/writes YAML files; `VectorStore` is a no-op; checkpoints are not persisted. Always test DB-dependent features in Docker.

7. **Settings API keys are masked on GET** — reading an API key immediately after writing returns the masked version. Write separate test cases for raw storage and masked response.
