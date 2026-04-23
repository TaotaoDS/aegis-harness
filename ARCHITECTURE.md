# AegisHarness — Architecture Reference

> **Version**: v0.0.1  
> **Accuracy date**: 2026-04-23 · 598 tests passing  
> **Audience**: AI agents and engineers working on this codebase.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Layout](#2-repository-layout)
3. [Infrastructure Layer](#3-infrastructure-layer)
4. [Core Orchestration Layer](#4-core-orchestration-layer)
5. [Resilience & Parallelism Engine](#5-resilience--parallelism-engine)
6. [State & Memory Management](#6-state--memory-management)
7. [API Layer](#7-api-layer)
8. [Frontend](#8-frontend)
9. [End-to-End Request Flow](#9-end-to-end-request-flow)
10. [Design Decisions & Guardrails](#10-design-decisions--guardrails)

---

## 1. System Overview

**AegisHarness** (v0.0.1) is a multi-agent code-generation orchestration platform. A user describes a software requirement; the system autonomously decomposes it, writes code, verifies it, and learns from mistakes — repeating until the requirement is met or human intervention is required.

```
User (Browser)
  │  HTTP / SSE
  ▼
Next.js Frontend  (port 3000)
  │  /api/proxy → fetch
  ▼
FastAPI Backend   (port 8000)   ← AegisHarness API v0.0.1
  │  Python async
  ▼
Core Orchestrator (pure Python)
  │  reads/writes
  ▼
PostgreSQL 16 + pgvector  (port 5432)
  workspaces/  (filesystem — generated code & artifacts)
```

**Key properties**:
- **Graceful degradation**: every integration (DB, OpenAI embeddings, tenacity, MCP) degrades silently to a no-op when unavailable.
- **Zero Blast Radius**: all refactors preserve exact API contracts; existing tests never break.
- **Compound Engineering flywheel**: every solved task feeds lessons back into the next run via `SolutionStore` + `VectorStore`.

---

## 2. Repository Layout

```
aegisharness/                          ← project root (dir: enterprise-harness)
├── main.py                            # CLI entry point (standalone run)
├── requirements.txt                   # Python dependencies
├── models_config.yaml                 # LLM routing table
├── alembic.ini                        # Alembic migration config
├── Dockerfile                         # Multi-stage backend image
├── docker-compose.yml                 # Full-stack one-click deploy
├── docker-compose.override.yml        # Local dev overrides
├── .env.example / .env.docker         # Environment templates
│
├── core_orchestrator/                 # Business logic — all pure Python
│   ├── __init__.py                    # Public API exports
│   ├── ceo_agent.py                   # Requirements interview + task planning
│   ├── architect_agent.py             # Code generation via tool-use LLM
│   ├── qa_agent.py                    # Code review agent
│   ├── evaluator.py                   # Sandbox syntax/lint verification
│   ├── reflection_agent.py            # Post-task reflection & lessons
│   ├── ce_orchestrator.py             # Top-level pipeline coordinator
│   ├── resilience_manager.py          # 3-layer escalation + wave scheduling
│   ├── parallel_executor.py           # Kahn BFS wave scheduler + ThreadPoolExecutor
│   ├── retry_utils.py                 # Exponential backoff (tenacity)
│   ├── model_router.py                # Multi-provider LLM routing
│   ├── llm_gateway.py                 # LLM conversation history manager
│   ├── llm_connector.py               # Provider SDK adapters (OpenAI / Anthropic)
│   ├── mcp_manager.py                 # MCP server registry
│   ├── vector_store.py                # pgvector semantic search (OpenAI embeddings)
│   ├── solution_store.py              # Filesystem YAML lessons + semantic search
│   ├── knowledge_manager.py           # Knowledge base file management
│   ├── workspace_manager.py           # Isolated per-job filesystem sandbox
│   ├── user_profile.py                # User persona & communication style
│   ├── pii_sanitizer.py               # PII redaction pipeline
│   ├── event_bus.py                   # In-process event emission (aegis_harness.audit.*)
│   ├── json_parser.py                 # Robust JSON extraction from LLM output
│   └── tests/                         # 598 pytest tests
│
├── api/                               # FastAPI application
│   ├── main.py                        # App factory, lifespan hooks, CORS
│   ├── job_runner.py                  # Background job execution
│   ├── job_store.py                   # In-memory job registry
│   ├── event_bridge.py                # EventBus → SSE bridge
│   ├── hitl_manager.py                # Human-in-the-loop approval gate
│   ├── interview_manager.py           # Live CEO interview state
│   ├── settings_service.py            # DB-backed key/value settings
│   └── routes/
│       ├── jobs.py                    # POST/GET /jobs
│       ├── stream.py                  # GET /jobs/{id}/events (SSE)
│       ├── approvals.py               # POST /jobs/{id}/approve|reject
│       ├── interview.py               # POST /jobs/{id}/interview/answer
│       ├── settings.py                # GET/PUT /settings/{key}
│       └── mcp.py                     # CRUD + probe /mcp/servers
│
├── db/                                # Database layer
│   ├── connection.py                  # Async engine, session factory, init/close
│   ├── models.py                      # SQLAlchemy ORM (5 tables)
│   ├── repository.py                  # Async CRUD functions
│   └── migrations/versions/
│       ├── 001_initial_schema.py      # jobs, events, checkpoints, solutions, settings
│       └── 002_add_embedding_column.py # solutions.embedding JSON column (v0.0.1)
│
└── web/                               # Next.js 14 frontend
    └── app/
        ├── layout.tsx                 # Root layout + nav
        ├── page.tsx                   # Job list dashboard
        ├── chat/                      # SSE streaming chat interface
        │   ├── page.tsx               # Phase state machine + EventSource
        │   └── components/
        │       ├── MessageBubble.tsx
        │       └── ChatInput.tsx
        ├── jobs/new/                  # Job creation form
        ├── settings/                  # 5-tab settings panel
        │   ├── page.tsx
        │   └── components/
        │       ├── ProfileTab.tsx
        │       ├── CEOTab.tsx
        │       ├── APIKeysTab.tsx
        │       ├── ModelsTab.tsx
        │       └── MCPTab.tsx         # MCP dynamic tool manager UI
        └── api/proxy/                 # Next.js route handlers → backend proxy
```

---

## 3. Infrastructure Layer

### 3.1 PostgreSQL 16 + pgvector

**Schema** (5 tables, managed by Alembic):

| Table | Purpose | Key Columns |
|---|---|---|
| `jobs` | Job metadata & status | `id` (PK, 8-char), `type`, `workspace_id`, `requirement`, `status` |
| `events` | Append-only SSE event log | `job_id` (FK idx), `seq`, `type`, `label`, `data` (JSON) |
| `checkpoints` | Phase resume state | `job_id` (PK), `phase`, `completed_tasks` (JSON), `current_task_index` |
| `solutions` | Workspace-scoped lessons + embeddings | `id`, `workspace_id` (idx), `problem`, `solution`, `embedding` (JSON) |
| `settings` | Global KV store | `key` (PK), `value` (JSON) |

**Migration chain**:
```
001_initial_schema     — jobs, events, checkpoints, solutions, settings
002_add_embedding_column — solutions.embedding JSON float[1536] (added v0.0.1)
```

**Migration workflow**:
```bash
alembic upgrade head          # apply all pending migrations
alembic revision -m "name"    # create new migration
```

### 3.2 Async Database Access

`db/connection.py` manages a single `AsyncEngine` + `async_sessionmaker`:

```python
await init_db()                         # call once at startup; safe no-op without DATABASE_URL
is_db_available() -> bool               # True after successful init
async with get_session() as session:    # AsyncSession with auto-commit
    ...
await close_db()                        # dispose engine on shutdown
```

**File-only mode**: when `DATABASE_URL` is unset, `init_db()` returns `False` and all DB operations become no-ops. The system continues to work using filesystem-only persistence.

### 3.3 Docker Deployment

`docker-compose.yml` defines three services:

| Service | Image | Port | Volume |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | `postgres_data` |
| `backend` | Custom `Dockerfile` | 8000 | `workspaces` |
| `frontend` | `web/Dockerfile` | 3000 | — |

**Quick start**:
```bash
cp .env.docker .env          # fill in API keys
docker compose up --build    # builds + runs migrations + starts all services
```

The backend `Dockerfile` is a multi-stage build: `python:3.12-slim` builder → installs deps → runtime stage copies only the venv + source → runs `alembic upgrade head` → starts `uvicorn`.

---

## 4. Core Orchestration Layer

### 4.1 Agent Pipeline

```
CEOAgent
  ├── reverse_interview()     ← asks clarifying questions until ≥95% confidence
  ├── create_plan()           ← decomposes requirement into task files
  └── delegate()              ← writes tasks/{id}.md with depends_on

ResilienceManager.run_all()
  └── [per task, in wave order]:
      ArchitectAgent.solve_task()   ← generates code via tool-use LLM
      Evaluator.run_eval()          ← syntax + lint sandbox check
      QAAgent.review_task()         ← LLM code review
      KnowledgeManager.append_lesson()  ← on retry success

ReflectionAgent
  └── reflect()               ← post-task lessons → SolutionStore

SolutionStore
  └── save() / format_as_context() / semantic_search()
```

### 4.2 CEOAgent

**File**: `core_orchestrator/ceo_agent.py`

State machine:
- **Green-field**: `idle → interviewing → planning → delegating → done`
- **Update mode**: `idle → update_planning → delegating → done`

Key behaviours:
- Runs a structured reverse-interview until `confidence ≥ 95` or `done: true` in the JSON response.
- Injects `SolutionStore.format_as_context()` (all past lessons) into the planning prompt.
- Respects `UserProfile.technical_level` — non-technical users get `options[]` arrays in interview questions (rendered as click-to-answer buttons in the Chat UI).
- Plan JSON schema includes `"depends_on": ["task_id"]` for declaring task dependencies.
- Writes each delegated task as `tasks/{task_id}.md` with a `- **Depends on:**` line parsed by `ResilienceManager._read_depends_on()`.

### 4.3 ArchitectAgent

**File**: `core_orchestrator/architect_agent.py`

- Receives a task file and generates code via **tool-use** (function calling) with a `write_file` tool.
- Injects `knowledge_context` (domain lessons) and `solutions_context` (past project lessons) into the system prompt.
- Forwards HITL approval requests to `HITLManager` when a dangerous tool call is detected.
- Tracks written files per `task_id` via `get_written_files(task_id)`.

### 4.4 Evaluator

**File**: `core_orchestrator/evaluator.py`

Runs sandbox checks on every file the Architect writes:
- Python: `ast.parse()` for syntax errors; optional `pyflakes` for lint.
- Timeout-protected subprocess calls.
- Returns `EvalResult(success, errors)`.

### 4.5 ModelRouter

**File**: `core_orchestrator/model_router.py`

Routes LLM calls to the correct provider based on `models_config.yaml`. Supported providers:
- `openai` — OpenAI API
- `anthropic` — Anthropic Claude API
- `nvidia` — NVIDIA NIM (OpenAI-compatible)
- `deepseek`, `zhipu`, `moonshot` — OpenAI-compatible third-party APIs

All outbound calls are wrapped with `with_retry()` (see §5.2) for automatic 429/5xx recovery.

### 4.6 UserProfile

**File**: `core_orchestrator/user_profile.py`

Stores user persona: `name`, `role`, `technical_level` (`"technical"` | `"non_technical"`), `language`, `notes`.

CEO interview and plan prompts adapt based on `technical_level`:
- **technical**: concise JSON-only responses, no options arrays.
- **non_technical**: friendly language, `options[]` in question responses for click-to-answer UX.

---

## 5. Resilience & Parallelism Engine

### 5.1 3-Layer Escalation

`ResilienceManager.run_task_loop(task_id)` implements a retry loop with three escalation levels:

| Layer | Trigger | Action |
|---|---|---|
| 1 — Context Reset | 1st fail (Eval or QA) | Inject feedback, retry with same model |
| 2 — Model Escalation | 2nd fail | Switch to `escalated_tool_llm` (higher-tier model) |
| 3 — Human Escalation | All retries exhausted OR token budget ≥ 80% | Write `escalations/{task_id}_escalation.md`, emit event |

**Token budget**: `tiktoken` counts tokens in every LLM gateway history; enforced via `_budget_exceeded()`.

**Thread safety**: `self._lock = threading.Lock()` guards `_token_usage` and `_results` accumulators when `parallel_workers > 1`.

### 5.2 Retry Utility — Exponential Backoff

**File**: `core_orchestrator/retry_utils.py`

```python
with_retry(fn, /, *args, max_attempts=4, wait_min=1.0, wait_max=60.0, multiplier=2.0, reraise=True, **kwargs)
```

- Built on `tenacity`; gracefully degrades (single attempt, no retry) when tenacity is not installed.
- `is_retryable(exc)`: retries on HTTP 429/5xx (via `exc.status_code`) and well-known transient class names (`RateLimitError`, `APIConnectionError`, `APITimeoutError`, `InternalServerError`, `ServiceUnavailableError`, `Timeout`, `ConnectionError`).
- Used in `ModelRouter` to wrap every `connector.call()` and `connector.call_with_tools()`.

### 5.3 Kahn BFS Wave Scheduler

**File**: `core_orchestrator/parallel_executor.py`

```python
wave_schedule(depends_on: Dict[str, List[str]]) -> List[List[str]]
```

- Pure-Python **Kahn's BFS** topological sort. O(n+e) time.
- Tasks with in-degree zero at the same time form a "wave" and can run concurrently.
- Raises `ValueError` on circular dependency.

```python
ParallelExecutor(workers: int = 1).run(task_fn, depends_on) -> Dict[str, Any]
```

- Submits each wave to `ThreadPoolExecutor(max_workers=workers)`.
- Waits for **all** futures in a wave before starting the next.
- Re-raises the first exception after the wave settles.
- **`workers=1` default** → identical sequential behaviour, backward-compatible.

**Dependency declaration** (in CEO task files):
```markdown
- **Depends on:** task_1, task_2
```
Parsed by `ResilienceManager._read_depends_on(task_id)`.

---

## 6. State & Memory Management

### 6.1 DB-Backed Checkpoints & Crash Recovery

**Table**: `checkpoints` (PK: `job_id`)  
**Columns**: `phase`, `completed_tasks` (JSON list), `current_task_index`, `data` (JSON dict), `updated_at`

```python
await save_checkpoint(session, job_id, phase, completed_tasks, current_task_index, data)
await load_checkpoint(session, job_id) -> Optional[Dict]
```

**Crash recovery** in `api/main.py` lifespan:
1. On startup, calls `_recover_jobs_from_db()`.
2. Jobs in `running/pending/waiting_approval` state are marked `"interrupted"`.
3. All persisted jobs reload into the in-memory `job_store`.
4. Operators see the full job history immediately after a restart.

### 6.2 SolutionStore — Compound Engineering Flywheel

**File**: `core_orchestrator/solution_store.py`  
**Storage**: individual YAML files at `workspaces/{workspace_id}/_workspace/solutions/{uuid8}.yaml`

```python
store.save({"problem": "...", "solution": "...", "type": "error_fix", "tags": [...]}) -> str
store.load_all() -> List[Dict]               # chronological order
store.format_as_context() -> str             # LLM-ready markdown (all lessons)
store.semantic_search(query, top_k=5) -> str # LLM-ready markdown (most relevant by cosine)
```

**Solution types**: `error_fix` | `architectural_decision` | `best_practice`

**Flywheel loop**:
```
execute → reflect → SolutionStore.save()
       → inject via format_as_context() / semantic_search()
       → execute better → capture → save() → repeat
```

### 6.3 VectorStore — Semantic Search (pgvector)

**File**: `core_orchestrator/vector_store.py`

```python
vs = get_vector_store()              # module-level singleton
await vs.embed_text(text)            # → List[float] (1536 dims) or None
await vs.upsert(solution_id, text)   # embeds + UPDATE solutions SET embedding
await vs.search_similar(query, top_k=5, workspace_id=None) -> List[Dict]
```

**Embedding model**: OpenAI `text-embedding-3-small` (1536 dimensions).  
**Similarity**: pure-Python cosine — `dot(a,b) / (|a| × |b|)`.  
**Storage**: `solutions.embedding` JSON float array (no pgvector PG extension required).

**Graceful degradation chain**:

| Missing resource | Behaviour |
|---|---|
| No `DATABASE_URL` | `upsert`/`search_similar` → `False`/`[]` |
| No `OPENAI_API_KEY` | `embed_text` → `None` |
| OpenAI API error | logged as WARNING, returns `None` |
| DB error | logged as WARNING, returns `[]` |

**Async/sync bridge** in `SolutionStore.semantic_search()`:
```python
# Running inside FastAPI (event loop already active):
with ThreadPoolExecutor() as pool:
    future = pool.submit(asyncio.run, vs.search_similar(query, top_k=top_k))
    results = future.result(timeout=10)
# Otherwise:
results = asyncio.run(vs.search_similar(query, top_k=top_k))
```

### 6.4 WorkspaceManager

**File**: `core_orchestrator/workspace_manager.py`

Provides an isolated per-job filesystem sandbox under `workspaces/{workspace_id}/`. Internal paths (solutions, escalations, etc.) auto-route to `_workspace/` subdirectories when `isolated=True`. No path traversal is possible.

### 6.5 Settings Service

**File**: `api/settings_service.py`

Global DB-backed key/value store:
```python
await get_setting(key) -> Optional[Any]
await set_setting(key, value)
```

**Keys used by AegisHarness**:

| Key | Type | Used by |
|---|---|---|
| `user_profile` | dict | CEOAgent interview style |
| `ceo_config` | dict | CEOAgent name + system prompt prefix |
| `api_keys` | dict | ModelRouter (returned masked on GET) |
| `model_config` | dict | ModelRouter default model |
| `mcp_servers` | list | MCPManager persistence |

---

## 7. API Layer

**Base URL**: `http://localhost:8000`  
**Version**: v0.0.1  
**App factory**: `api/main.py`

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Health check + DB status (`{"version": "0.0.1"}`) |
| `POST` | `/jobs` | Create and start a new job |
| `GET` | `/jobs` | List all jobs |
| `GET` | `/jobs/{id}` | Get job detail |
| `GET` | `/jobs/{id}/events` | **SSE stream** of job events |
| `POST` | `/jobs/{id}/approve` | Approve a HITL gate |
| `POST` | `/jobs/{id}/reject` | Reject a HITL gate |
| `POST` | `/jobs/{id}/interview/answer` | Submit answer to CEO interview question |
| `GET` | `/settings/{key}` | Read a setting value |
| `PUT` | `/settings/{key}` | Write a setting value |
| `GET` | `/mcp/servers` | List registered MCP servers |
| `POST` | `/mcp/servers` | Register a new MCP server |
| `PUT` | `/mcp/servers/{id}` | Update a server |
| `DELETE` | `/mcp/servers/{id}` | Remove a server |
| `POST` | `/mcp/servers/{id}/probe` | Probe server + discover tools |

### SSE Event Types

| Event type | Payload fields |
|---|---|
| `job.started` | — |
| `ceo.question` | `question`, `options?`, `confidence` |
| `ceo.plan_ready` | — |
| `architect.solve_complete` | `task_id`, `attempt` |
| `evaluator.pass` / `evaluator.fail` | `task_id`, `file_count` / `error` |
| `evaluator.zero_files` | `task_id`, `attempt` |
| `qa.pass` / `qa.fail` | `task_id`, `attempt` |
| `resilience.escalated` | `task_id`, `attempts`, `escalation_level` |
| `pipeline.execution_complete` | `passed`, `escalated`, `token_usage` |
| `job.completed` / `job.failed` | — |
| `hitl.approval_required` | `task_id`, `tool_call` |

### Lifespan Hooks

On **startup** (`api/main.py::lifespan`):
1. `init_db()` — connects to PostgreSQL (skipped gracefully if no `DATABASE_URL`).
2. `_recover_jobs_from_db()` — reloads job history; marks in-flight jobs as `"interrupted"`.

On **shutdown**:
1. `close_db()` — disposes the SQLAlchemy async engine.

---

## 8. Frontend

**Framework**: Next.js 14 (App Router)  
**Styling**: Tailwind CSS  
**Package name**: `aegis-harness-web` v0.0.1  
**Base URL**: `http://localhost:3000`

### Pages

| Route | Description |
|---|---|
| `/` | Job list dashboard |
| `/chat` | SSE streaming chat interface |
| `/jobs/new` | Job creation form |
| `/settings` | 5-tab settings panel |

### Chat Page — SSE Streaming UI (`/chat`)

**File**: `web/app/chat/page.tsx`

Phase state machine:
```
idle → creating (POST /jobs) → streaming (EventSource) → done | error
```

- `ceo.question` events render as bot bubbles; `options[]` arrays become clickable violet buttons for non-technical users.
- System events (`ceo.plan_ready`, `pipeline.execution_complete`, etc.) render as centered status pills.
- Terminal events (`job.completed` → `done`, `job.failed` → `error`) lock the input.

**Components**:
- `MessageBubble` — `user` (right, blue) / `bot` (left, violet) / `system` (centered pill); renders `options[]` as action buttons.
- `ChatInput` — auto-resize textarea; Enter submits; Shift+Enter newline; disabled during processing.

### Settings Page — 5-Tab Panel (`/settings`)

**File**: `web/app/settings/page.tsx`

| Tab | Settings key | Description |
|---|---|---|
| 👤 用户画像 | `user_profile` | Name, role, technical level, language, notes |
| 🤖 CEO 配置 | `ceo_config` | Agent name + system prompt prefix |
| 🔑 API Key | `api_keys` | Provider keys (masked on return) |
| ⚡ 模型 | `model_config` | Default model selection |
| 🔧 MCP 工具 | `/mcp/*` | MCP dynamic tool manager |

### MCPTab — Dynamic Tool Manager (`/settings` → MCP 工具)

**File**: `web/app/settings/components/MCPTab.tsx`

- Add server form: name + URL + description → `POST /mcp/servers`.
- Server list: status indicator (● connected / ○ unknown/error), discovered tool name tags.
- Per-server: 🔍 Probe (`POST /mcp/servers/{id}/probe`) · 🗑 Delete.
- Full list refreshes after every mutation.

---

## 9. End-to-End Request Flow

### Happy Path — New Job via Chat UI

```
1.  User types requirement in /chat → POST /api/proxy/jobs
2.  Backend creates job, launches background task (api/job_runner.py)
3.  Frontend opens EventSource → /api/proxy/jobs/{id}/events

4.  [CEO Interview]
    CEOAgent.reverse_interview()
    → each question: emit ceo.question SSE event
    → options[] rendered as buttons in Chat UI
    → user answers → POST /jobs/{id}/interview/answer
    → repeat until confidence ≥ 95

5.  [Planning]
    CEOAgent.create_plan()
    → SolutionStore.format_as_context()   (all past lessons)
    → SolutionStore.semantic_search(req)  (top-5 similar by cosine)
    → both injected into planning prompt
    → emit ceo.plan_ready

6.  [Wave-Parallel Execution]
    ResilienceManager.run_all()
    → wave_schedule(depends_on)  ← Kahn BFS
    → ParallelExecutor.run(run_task_loop, depends_on)
    → per task: ArchitectAgent → Evaluator → QAAgent
    → failures escalate through 3 layers
    → success: KnowledgeManager.append_lesson()

7.  [Reflection]
    ReflectionAgent.reflect()
    → SolutionStore.save(lesson)
    → VectorStore.upsert(id, text)   ← stores embedding in DB

8.  job.completed SSE → frontend transitions to done state
```

### Semantic Memory Injection (subsequent jobs)

```
CEOAgent.create_plan()
  → SolutionStore.format_as_context()   # full lesson list (text match)
  → SolutionStore.semantic_search(req)  # top-k by OpenAI embedding cosine
  → inject both blocks into LLM system prompt
```

---

## 10. Design Decisions & Guardrails

### Embeddings without pgvector Extension

Embeddings are stored as `JSON` float arrays in PostgreSQL (column `solutions.embedding`). Cosine similarity is computed in pure Python (`_cosine_similarity`). This avoids requiring the `pgvector` PostgreSQL extension or the `pgvector` Python package. For collections up to ~50k entries, Python cosine is fast enough. Upgrade path: add `pgvector>=0.3.0` to `requirements.txt`, migrate column to `vector(1536)` with `alembic`, and update `search_similar` to use `<=>` operator.

### Tenacity Graceful Degradation

`retry_utils.py` wraps `tenacity` in a `try/except ImportError`. If the package is missing, `with_retry()` calls the function once with no retry logic. The system works in restricted environments.

### `parallel_workers=1` Default

`ResilienceManager` and `ParallelExecutor` default to 1 worker. This keeps execution deterministic and preserves backward compatibility with all tests written before the parallel engine was introduced. Increase `parallel_workers` only when task functions are confirmed thread-safe.

### Thread Safety Scope

`threading.Lock()` in `ResilienceManager` guards only `_token_usage` and `_results`. Individual task loops are independent (each writes to unique workspace paths and DB rows), so no broader lock is needed.

### Async/Sync Bridge

`SolutionStore.semantic_search()` (sync) calls `VectorStore.search_similar()` (async). The bridge detects an active event loop and uses `ThreadPoolExecutor` + `asyncio.run()` in that case; outside any loop it calls `asyncio.run()` directly.

### PII Sanitization Order

`default_pipeline()` runs `sanitize_id_card` before `sanitize_credit_card` because 18-digit Chinese ID card numbers match the credit card regex. Custom pipelines must maintain this order.

### Workspace Isolation

All agent file I/O goes through `WorkspaceManager`, which confines reads and writes to `workspaces/{workspace_id}/`. No path traversal is possible. Secrets (API keys, user data) never leave the settings service.

### Settings API Key Masking

`GET /settings/api_keys` returns values masked to `***…xxxx` (last 4 chars). Raw keys are stored in the DB and injected at call time only.
