# AegisHarness

**v0.1.0** · Production-grade AI Agent Harness — deterministic auth, multi-tenancy, semantic memory, and MCP tool management for LLM workflows.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/) [![Next.js 15](https://img.shields.io/badge/next.js-15-black)](https://nextjs.org/) [![PostgreSQL 16](https://img.shields.io/badge/postgresql-16-336791)](https://www.postgresql.org/) [![Tests 598](https://img.shields.io/badge/tests-598%20passing-brightgreen)]() [![License MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](./README.md) | [中文](./README.zh-CN.md)

---

[Overview](#overview) · [Core Features](#core-features) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Configuration](#configuration) · [Project Structure](#project-structure) · [Development](#development) · [Contributing](#contributing)

---

## Overview

Large language models are probabilistic by nature — they hallucinate, forget context, and have no concept of "who is asking." **AegisHarness is the infrastructure layer that makes LLM-powered agents production-ready.**

Think of it as the harness around a racecar engine: the engine (LLM) is powerful but unpredictable on its own. The harness provides the frame, the steering, and the safety systems — so the power can actually be used. Concretely, AegisHarness gives any LLM backend:

| What bare LLMs lack | What AegisHarness provides |
|---|---|
| No identity | JWT multi-tenancy — every request is scoped to a verified user and an isolated tenant |
| No memory | Semantic vector search over past solutions — agents learn from prior runs, not just the current context window |
| No tools | Hot-pluggable MCP tool manager — agents call external services without a restart |
| No fault tolerance | 3-layer fault-recovery loop — a single model failure never kills an entire pipeline |

The result is a **deterministic harness around a non-deterministic core**: you own the workflow; the LLM writes the code.

---

## Core Features

### 1. Enterprise-grade Multi-tenancy & Auth

Every resource — jobs, solutions, settings, MCP servers — is scoped to a `tenant_id`. Sprints A–D (v0.1.0) delivered a complete JWT auth stack with full row-level isolation.

| Capability | Detail |
|---|---|
| Token design | HS256 JWT access token (15 min TTL) + opaque UUID refresh token (7 days, stored as bcrypt hash) |
| Cookie transport | `aegis_access` + `aegis_refresh` — both `httpOnly`, CSRF-safe |
| Roles | `owner` / `admin` / `member` with route-level guards (`require_admin`, `require_owner`) |
| Row-level isolation | All tables carry `tenant_id`; settings PK is `(tenant_id, key)` — each tenant gets independent config |
| Invite flow | Owner generates single-use invite tokens; recipients self-register into the same tenant |
| Backward compat | Pre-auth rows backfilled to `BOOTSTRAP_TENANT_ID` — zero data migration required |
| API key encryption | Fernet symmetric encryption at rest; UI shows last 4 chars only |
| **DEV_MODE** | When `SECRET_KEY` is **unset**, auth is fully bypassed. The backend returns a synthetic `dev@localhost` owner and the frontend never redirects to `/login`. Full feature evaluation with zero credentials. |

### 2. BYOM — Bring Your Own Model (17 Providers)

Every LLM call goes through a YAML-configured `ModelRouter`. Switching models requires one line in `models_config.yaml` — no code change, no restart.

All providers share a single, pure-`urllib` connector. No additional provider SDK is needed beyond the two first-party ones (`openai`, `anthropic`) already in `requirements.txt`.

**Global (7)**

| Provider | Notes |
|---|---|
| Anthropic | Claude Sonnet, Claude Opus |
| OpenAI | GPT-4o and any OpenAI-compatible endpoint |
| Google Gemini | via OpenAI-compatible proxy |
| Mistral AI | via OpenAI-compatible endpoint |
| Groq | via OpenAI-compatible endpoint |
| xAI (Grok) | via OpenAI-compatible endpoint |
| Together AI | via OpenAI-compatible endpoint |

**China Ecosystem (8)**

| Provider | Notes |
|---|---|
| DeepSeek | V3 / R1 reasoning |
| Alibaba Qwen | Qwen-Long / Qwen-Max |
| Zhipu GLM | GLM-5, GLM-5-Turbo, GLM-4.7 |
| Moonshot / Kimi | 8k / 128k context |
| Baidu ERNIE | via OpenAI-compatible proxy |
| MiniMax | via OpenAI-compatible endpoint |
| Yi (01.AI) | via OpenAI-compatible endpoint |
| Doubao (ByteDance) | via OpenAI-compatible endpoint |

**Local / Offline (3)**

| Provider | Notes |
|---|---|
| **Ollama** | Fully offline; embedding backend also uses `urllib` only — zero network dependency |
| **vLLM** | Self-hosted OpenAI-compatible server |
| Any OpenAI-compatible | Point `base_url` to any server in `models_config.yaml` |

For local providers, no API key is required — only the endpoint URL and model identifier.

### 3. Concurrent Task Scheduling & 3-Layer Fault Recovery

The orchestrator decomposes each project into a task graph and executes independent tasks in parallel waves.

**Scheduling — Kahn BFS (`parallel_executor.py`)**

```
Task dependency graph  →  wave_schedule()  →  [ [A], [B, C], [D] ]
                                                   ↑     ↑       ↑
                                                wave 1  wave 2  wave 3
```

`wave_schedule()` uses Kahn's BFS to topologically sort tasks into waves. `ParallelExecutor` submits each wave to a `ThreadPoolExecutor` and waits for all futures before advancing to the next wave. Circular dependencies are detected and raise a clear `ValueError`.

**3-Layer Fault Recovery (`resilience_manager.py`)**

| Layer | Trigger | Action |
|---|---|---|
| **1 — Context Reset** | First code-review failure | Inject evaluator feedback; retry with the same model |
| **2 — Model Escalation** | Second consecutive failure | Switch to a higher-tier `escalated_tool_llm` |
| **3 — Human Gate** | Third failure **or** token budget ≥ 80% | Write escalation report to workspace; pause for HITL approval |

All LLM calls additionally wrap a `tenacity` exponential back-off retry (1 s → 60 s, 4 attempts). When `tenacity` is not installed the call executes once with no retry and no import error — zero blast radius.

### 4. Dynamic MCP Tool Manager

MCP (Model Context Protocol) servers extend the agent with external tools — web search, code execution, database queries, and more.

- **Hot-plug**: Add, update, or remove servers via the Settings UI or REST API. No restart required.
- **Per-tenant registry**: Each tenant maintains its own server list, persisted in the settings table and lazily restored on first API call.
- **Zero-dependency probe**: `POST /mcp/servers/{id}/probe` discovers available tools over `urllib.request` — no extra HTTP library.

```bash
# Register a tool server
curl -X POST http://localhost:8000/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{"name": "my-tools", "url": "http://localhost:9000"}'

# Probe connectivity + discover tools
curl -X POST http://localhost:8000/mcp/servers/{id}/probe
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser  (Next.js 15 · App Router · Tailwind CSS)              │
│                                                                  │
│  Shell.tsx ──► route guard (useAuth)                            │
│  /chat     ──► SSE event stream ──► MessageBubble / Timeline    │
│  /settings ──► APIKeysTab · ModelsTab · MCPTab · ProfileTab     │
│  /login /register /invite/[token]   (public routes)             │
└───────────────────────────┬─────────────────────────────────────┘
                            │  HTTPS + httpOnly cookies
                            │  /api/proxy/** (cookie-forwarding reverse proxy)
┌───────────────────────────▼─────────────────────────────────────┐
│  FastAPI  (Uvicorn · 2 workers · async)                         │
│                                                                  │
│  /auth        register · login · refresh · invite · me          │
│  /jobs        create · list · detail · cancel                   │
│  /jobs/{id}/stream   SSE stream (keepalive every 15 s)          │
│  /approvals          HITL gate (approve / reject)               │
│  /settings           API keys · model config (per-tenant)       │
│  /mcp                server CRUD + probe                        │
│                                                                  │
│  Lifespan: init_db() · _recover_jobs_from_db() · close_db()    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Core Orchestrator  (pure Python · no framework)                │
│                                                                  │
│  CEOAgent          (≥95% confidence clarifying interview)       │
│    └─► ArchitectAgent  (tool-use code generation)               │
│          └─► Evaluator     (ast · pyflakes · subprocess)        │
│                └─► QAAgent     (code review)                    │
│                      └─► ReflectionAgent (lesson extraction)    │
│                                                                  │
│  ModelRouter       (YAML routing · 30 s cache · ${VAR} interp.) │
│  LLMConnector      (OpenAI / Anthropic adapters · urllib)       │
│  ParallelExecutor  (Kahn BFS waves · ThreadPoolExecutor)        │
│  ResilienceManager (3-layer escalation · token budget guard)    │
│  MCPManager        (hot-plug · per-tenant · urllib probe)       │
│  VectorStore       (pgvector upsert · Python cosine fallback)   │
│  SolutionStore     (YAML lessons · workspace-scoped)            │
│  PIISanitizer      (composable redaction pipeline)              │
└───────────────────────────┬─────────────────────────────────────┘
                            │  asyncpg · SQLAlchemy 2.0 async
┌───────────────────────────▼─────────────────────────────────────┐
│  PostgreSQL 16 + pgvector                                       │
│                                                                  │
│  tenants · users · refresh_tokens · workspaces                  │
│  jobs · job_events · checkpoints                                │
│  solutions  (embedding JSONB 1536-dim, ready for pgvector v2)   │
│  settings   PK: (tenant_id, key)                                │
└─────────────────────────────────────────────────────────────────┘
```

**Request flow (happy path)**

1. Browser sends `POST /api/proxy/jobs` with the `aegis_access` cookie.
2. Next.js proxy forwards to FastAPI; `get_current_user` validates JWT and resolves `tenant_id`.
3. CEOAgent conducts a structured requirements interview until ≥ 95% confidence.
4. Architect decomposes work into a dependency graph; `wave_schedule` computes parallel waves.
5. Each wave runs concurrently; Evaluator + QA gate each task; ResilienceManager handles failures.
6. ReflectionAgent extracts lessons into SolutionStore; semantic embeddings upserted to pgvector.
7. The SSE stream delivers real-time events to the browser throughout.

For the full design reference see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Quick Start

### Option A — Docker (Recommended)

```bash
git clone <repo-url>
cd enterprise-harness

# Copy the Docker env template.
# API keys are optional — see DEV_MODE note below.
cp .env.docker .env

# Start postgres, backend, and frontend
docker compose up --build
```

| Service | URL |
|---|---|
| Web Console | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

> **DEV_MODE — Zero Regression**
>
> If `SECRET_KEY` is **not set** in `.env`, the backend operates in development mode:
> all auth checks are bypassed, a synthetic `dev@localhost` owner is returned for
> every request, and the frontend never redirects to `/login`.
>
> The complete feature set — multi-tenant settings, MCP tools, the full orchestrator
> pipeline, and semantic memory — is available without any API keys or credentials.
>
> To activate production auth, add:
> ```bash
> SECRET_KEY=$(openssl rand -hex 32)
> ```

### Option B — Local Development

Prerequisites: Python 3.12+, Node 20+, PostgreSQL 16

```bash
# 1. Python backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # set DATABASE_URL + any API keys
alembic upgrade head            # run all 5 schema migrations

uvicorn api.main:app --reload --port 8000

# 2. Next.js frontend (separate terminal)
cd web
npm install
npm run dev                     # http://localhost:3000
```

Without `DATABASE_URL` the system runs in **file-only mode** — full orchestration functionality, but without DB persistence and semantic search.

### Option C — CLI (Orchestrator only, no web UI)

```bash
python main.py                                     # new workspace + interactive CEO interview
python main.py --workspace <id>                    # resume an existing workspace
python main.py --workspace <id> --update "fix X"   # incremental update run
python main.py --workspace <id> --reset            # clear checkpoint, re-run from scratch
```

---

## Configuration

### API Keys

Keys can be set in three equivalent ways (precedence: DB settings > `.env` > system env):

1. **Settings UI** → API Keys tab — values masked on read (last 4 chars only).
2. **`.env` file** — loaded at startup.
3. **System environment variables** — useful for Docker and CI pipelines.

| Variable | Provider |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `OPENAI_API_KEY` | OpenAI GPT |
| `NVIDIA_API_KEY` + `NVIDIA_BASE_URL` | NVIDIA NIM |
| `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL` | DeepSeek V3 / R1 |
| `ZHIPU_API_KEY` + `ZHIPU_BASE_URL` | Zhipu GLM |
| `MOONSHOT_API_KEY` + `MOONSHOT_BASE_URL` | Moonshot / Kimi |

> All keys are stored encrypted (Fernet) in the database when saved through the UI.
> They are never sent to any third-party server.

### Model Routing (`models_config.yaml`)

```yaml
models:
  my-model:
    provider: openai               # "openai" handles all OpenAI-compatible APIs
    model_name: gpt-4o
    api_key_env: OPENAI_API_KEY    # env var name, or inline ${VAR} interpolation
    base_url: null                 # null = use provider default
    max_tokens: 8192
    temperature: 0.2

routes:
  - match: { role: architect }
    model: my-model
  - match: {}                      # catch-all default
    model: my-model

execution:
  max_retries: 3          # Architect retry limit per task
  eval_timeout: 30        # Evaluator sandbox timeout (seconds)
  token_budget: 100000    # Global token cap per pipeline run
  token_threshold: 0.8    # Escalate to human at 80% budget usage

embedding:
  provider: openai                 # set "ollama" for fully offline operation
  model: text-embedding-3-small
  api_key_env: OPENAI_API_KEY
```

### Auth & Multi-tenancy

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | _(unset)_ | JWT signing secret. Absent = DEV_MODE (all auth bypassed). |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token TTL |

### Settings via Web Console

All settings persist to the database — no restart required.

| Tab | Purpose |
|---|---|
| 👤 User Profile | Name, role, technical level — CEOAgent adapts interview style accordingly |
| 🤖 CEO Config | Agent display name + custom system prompt prefix |
| 🔑 API Keys | Provider API key management (masked; Fernet-encrypted at rest) |
| ⚡ Models | Default model routing selection |
| 🔧 MCP Tools | Register / probe / remove MCP tool servers |

### Offline / Air-gapped Deployment

Set `embedding.provider: ollama` in `models_config.yaml` and point all model routes to a local Ollama or vLLM instance. The embedding client uses only Python's `urllib.request` — no OpenAI SDK, no internet connection required.

---

## Project Structure

```
enterprise-harness/
├── core_orchestrator/         # Pure Python business logic (22 modules · 48 test files)
│   ├── ceo_agent.py           # Clarifying interview (≥95% confidence threshold)
│   ├── architect_agent.py     # Code generation via tool-use LLM
│   ├── qa_agent.py            # Code review agent
│   ├── evaluator.py           # Sandbox: ast · pyflakes · subprocess
│   ├── reflection_agent.py    # Lesson extraction → SolutionStore
│   ├── ce_orchestrator.py     # Pipeline coordinator (CEO→Architect→QA→Reflect)
│   ├── resilience_manager.py  # 3-layer escalation + token budget circuit breaker
│   ├── parallel_executor.py   # Kahn BFS wave scheduler + ThreadPoolExecutor
│   ├── retry_utils.py         # Exponential backoff (tenacity optional, degrades gracefully)
│   ├── model_router.py        # YAML-driven multi-provider routing (30 s TTL cache)
│   ├── llm_connector.py       # OpenAI / Anthropic adapter protocol + registry
│   ├── mcp_manager.py         # Hot-plug MCP server registry (urllib probe)
│   ├── vector_store.py        # pgvector upsert + Python cosine similarity fallback
│   ├── solution_store.py      # YAML lesson library (workspace-scoped)
│   ├── pii_sanitizer.py       # Composable PII redaction pipeline (30 tests)
│   └── tests/                 # 598 pytest tests across all modules
│
├── api/                       # FastAPI application (8 modules)
│   ├── main.py                # App factory · lifespan hooks · CORS · crash recovery
│   ├── auth.py                # JWT creation/validation · DEV_MODE logic
│   ├── deps.py                # FastAPI Depends: CurrentUser · require_admin · require_owner
│   └── routes/                # auth · jobs · stream · approvals · interview · settings · mcp
│
├── db/                        # Database layer
│   ├── models.py              # SQLAlchemy ORM (10 tables incl. auth + workspace)
│   ├── repository.py          # Async CRUD (15 k LOC)
│   ├── connection.py          # asyncpg engine · session factory
│   └── migrations/            # Alembic revisions 001–005
│       ├── 001_initial_schema.py
│       ├── 002_add_embedding_column.py
│       ├── 003_add_auth_tables.py
│       ├── 004_add_workspaces.py
│       └── 005_tenant_scope_existing_tables.py
│
├── web/                       # Next.js 15 frontend
│   ├── app/                   # App Router: dashboard · chat · jobs · settings · auth · onboarding
│   ├── components/            # Shell · Sidebar · MessageBubble · InterviewPanel · Timeline
│   ├── lib/auth/              # AuthProvider · useAuth() · token refresh
│   ├── lib/i18n/              # useT() hook · en.ts · zh.ts (18 localized components)
│   └── hooks/                 # useEventStream (SSE · auto-reconnect · dedup)
│
├── workspaces/                # Generated code artifacts (volume-mounted · git-ignored)
├── knowledge_base/            # Curated lesson library (pre-trained)
├── models_config.yaml         # LLM routing configuration
├── docker-compose.yml         # Production stack (postgres · backend · frontend)
├── docker-compose.override.yml # Local dev overrides (hot-reload)
├── Dockerfile                 # Backend multi-stage image (non-root user harness uid 1000)
├── .env.example               # Environment variable template
├── ARCHITECTURE.md            # Full system design reference
└── AGENTS.md                  # Agent operating manual
```

---

## Development

### Running Tests

```bash
pytest                           # all 598 tests
pytest core_orchestrator/tests/  # orchestrator unit tests only
pytest -k test_resilience        # filter by name
pytest --cov=core_orchestrator --cov-report=term-missing  # coverage report
```

### Database Migrations

```bash
alembic upgrade head                                  # apply all pending migrations
alembic revision --autogenerate -m "describe change"  # generate a new revision
alembic downgrade -1                                  # roll back one revision
alembic current                                       # show current revision
```

### Adding a New LLM Provider

1. Add an entry under `models:` in `models_config.yaml` with `provider: openai`. All OpenAI-compatible APIs work without any code changes.
2. If the provider requires a non-standard auth scheme, implement `LLMConnector` in `core_orchestrator/llm_connector.py` and register it with `register_connector("my-provider", MyConnector())`.
3. Add the API key env var to `.env.example` and the onboarding provider catalogue (`web/app/onboarding/providers.ts`).

### SSE Event Reference

| Event | Key Payload Fields | Description |
|---|---|---|
| `pipeline.start` | `job_id` | Pipeline begins |
| `agent.thinking` | `agent`, `message` | Agent producing output |
| `task.complete` | `task_id`, `output` | Single task finished |
| `hitl.required` | `task_id`, `reason` | Human approval gate triggered |
| `pipeline.complete` | `artifacts` | All tasks done; files available |
| `pipeline.error` | `error` | Unrecoverable failure |

---

## Contributing

**Zero blast radius** — every change must leave the system at least as functional as before.

- **Test-first**: Add or update tests before touching production code. The 598-test suite is the regression gate; all tests must pass before any merge.
- **Graceful degradation**: If you introduce an optional dependency, the system must work correctly when that dependency is absent. Use the `tenacity` and `pgvector` integrations as reference patterns.
- **No global state**: All mutations are scoped to a workspace or tenant. Thread safety is assumed only within a single task's execution context.
- **Preserve API contracts**: Backend route signatures and SSE event shapes are consumed by the frontend. Breaking changes require coordinated updates to both layers.

Pull requests should include:
1. A description of the problem being solved.
2. Test coverage for the new behaviour.
3. An entry in `CHANGELOG.md` under `[Unreleased]`.

---

## License

MIT
