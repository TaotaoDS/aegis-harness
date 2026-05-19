# AegisHarness

**v0.3.0** · Production-grade AI Agent Harness — deterministic auth, multi-tenancy, semantic knowledge graph, generative UI, cross-repo fusion analysis, skill dynamic loading, and MCP tool management for LLM workflows.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/) [![Next.js 15](https://img.shields.io/badge/next.js-15-black)](https://nextjs.org/) [![PostgreSQL 16](https://img.shields.io/badge/postgresql-16-336791)](https://www.postgresql.org/) [![Tests 1094](https://img.shields.io/badge/tests-1094%20passing-brightgreen)]() [![License MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](./README.md) | [中文](./README.zh-CN.md)

---

[Overview](#overview) · [Core Features](#core-features) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Configuration](#configuration) · [Project Structure](#project-structure) · [Development](#development) · [Contributing](#contributing)

> **What's new in v0.3.0** — Fusion Architect Agent for cross-repo analysis, Skill dynamic loading from compound knowledge, LLM-as-Judge quality gate, deep context compaction (tool output spill + LLM summarization), FinOps billing engine, sandbox isolation (ContentPreScreener + SandboxFactory), and security guardrails (PromptGuard + ContentModerator). 1094 tests passing.

---

## Overview

Large language models are probabilistic by nature — they hallucinate, forget context, and have no concept of "who is asking." **AegisHarness is the infrastructure layer that makes LLM-powered agents production-ready.**

Think of it as the harness around a racecar engine: the engine (LLM) is powerful but unpredictable on its own. The harness provides the frame, the steering, and the safety systems — so the power can actually be used. Concretely, AegisHarness gives any LLM backend:

| What bare LLMs lack | What AegisHarness provides |
|---|---|
| No identity | JWT multi-tenancy — every request is scoped to a verified user and an isolated tenant |
| No memory | Semantic knowledge graph + vector search — agents learn from prior runs and ingested documents |
| No tools | Hot-pluggable MCP tool manager — agents call external services without a restart |
| No fault tolerance | 3-layer fault-recovery loop — a single model failure never kills an entire pipeline |
| No human oversight | HITL approval gates — sensitive writes and escalations pause for human confirmation |
| No session continuity | PostgreSQL-backed chat history — conversations persist and resume across page reloads |
| No quality assurance | LLM-as-Judge — hallucination / accuracy / relevance scoring before any output ships |
| No cross-repo learning | Fusion Architect — clone, analyse, and synthesise architecture from multiple repositories |
| No reusable skills | Skill dynamic loading — compound knowledge auto-promotes to discoverable Markdown skills |

The result is a **deterministic harness around a non-deterministic core**: you own the workflow; the LLM writes the code.

---

## Core Features

### 1. Enterprise-grade Multi-tenancy & Auth

Every resource — jobs, solutions, settings, MCP servers, knowledge nodes — is scoped to a `tenant_id`. The auth stack delivers complete JWT authentication with full row-level isolation.

| Capability | Detail |
|---|---|
| Token design | HS256 JWT access token (15 min TTL) + opaque UUID refresh token (7 days, stored as bcrypt hash) |
| Cookie transport | `aegis_access` + `aegis_refresh` — both `httpOnly`, CSRF-safe |
| Roles | `super_admin` / `owner` / `admin` / `member` with route-level guards |
| Row-level isolation | All tables carry `tenant_id`; settings PK is `(tenant_id, key)` — each tenant gets independent config |
| Invite flow | Owner generates single-use invite tokens; recipients self-register into the same tenant |
| Transparent 401 recovery | Next.js proxy auto-refreshes expired tokens and retries the original request — frontend never sees 401 |
| Session expired modal | If refresh also fails, a non-disruptive login overlay appears without clearing UI state |
| API key encryption | Fernet symmetric encryption at rest; UI shows last 4 chars only |
| **DEV_MODE** | When `SECRET_KEY` is **unset**, auth is fully bypassed. The backend returns a synthetic `dev@localhost` owner and the frontend never redirects to `/login`. Full feature evaluation with zero credentials. |

### 2. BYOM — Bring Your Own Model (18+ Providers)

Every LLM call goes through a YAML-configured `ModelRouter`. Switching models requires one line in `models_config.yaml` — no code change, no restart.

All providers share a single, pure-`urllib` connector. No additional provider SDK is needed beyond the two first-party ones (`openai`, `anthropic`).

**Unified Gateway**

| Provider | Notes |
|---|---|
| **OpenRouter** ⭐ | One key → 300+ models (Claude / GPT / Gemini / Llama / DeepSeek, etc.) — recommended starting point |

**Global Providers**

| Provider | Notes |
|---|---|
| Anthropic | Claude Sonnet 4, Claude Opus 4 |
| OpenAI | GPT-4o and any OpenAI-compatible endpoint |
| Google Gemini | Gemini 2.0 Flash, Gemini Pro 1.5 |
| Mistral AI | mistral-large-2411 |
| Groq | llama-3.3-70b-versatile (ultra-fast inference) |
| xAI (Grok) | grok-2-latest |
| Together AI | Meta Llama and other open models |
| NVIDIA NIM | 200+ open-source models; free tier 1,000 calls |

**China Ecosystem**

| Provider | Notes |
|---|---|
| DeepSeek | V3 / R1 reasoning; very cost-effective |
| Alibaba Qwen | Qwen 2.5 72B and Qwen-Max series |
| Zhipu GLM | GLM-5, GLM-5-Turbo, GLM-4.7 |
| Moonshot / Kimi | 8k / 128k long-context |
| Baidu ERNIE | ERNIE 4.5 |
| MiniMax | abab6.5s-chat |
| 01.AI (Yi) | yi-large |
| ByteDance Doubao | doubao-pro-32k |

**Local / Offline**

| Provider | Notes |
|---|---|
| **Ollama** | Fully offline; embedding client also uses `urllib` only — zero network dependency |
| **vLLM** | Self-hosted OpenAI-compatible server |
| Any OpenAI-compatible | Point `base_url` to any server in `models_config.yaml` |

Keys saved through the Settings UI are automatically bridged into the model router via `key_injector.py` — no restart required.

### 3. AI Workspace — Knowledge Graph + Generative Chat

The **AI Workspace** (`/knowledge`) is the primary user interface, combining a knowledge graph, document ingestion, and a powerful generative chat assistant.

**Knowledge Graph**
- Upload PDFs, TXT files, or crawl URLs — each document becomes a graph node
- LLM extracts 5–10 key concepts per document, creating concept nodes linked to the source
- Auto-linking: semantic similarity search creates `related_concept` and `semantically_related` edges between nodes across documents
- Interactive D3.js graph: pan, zoom, click nodes to set chat context

**Generative Chat (WorkspaceChat)**
- Dual-pane layout: knowledge graph on the left, chat on the right (resizable divider)
- Type `/task <requirement>` to launch a full multi-agent pipeline inline
- Task progress renders as a live **TaskCard** with SSE event stream
- Interactive cards appear inline: CEO interview questions and HITL approval requests render directly in the chat — no page navigation required
- Answered/approved cards lock to a read-only state; the conversation history is preserved

**Chat Session Persistence**
- All conversations are stored in PostgreSQL (`chat_sessions` + `chat_messages` tables)
- Session resumes across page reloads — scroll position and message history are restored
- **History Drawer**: slide-in panel listing recent sessions; click any session to restore it
- New session button resets the chat while preserving the knowledge context

### 4. Concurrent Task Scheduling & 3-Layer Fault Recovery

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

All LLM calls additionally wrap a `tenacity` exponential back-off retry (1 s → 60 s, 4 attempts). When `tenacity` is not installed the call executes once with no retry — zero import error.

### 5. Human-in-the-Loop (HITL) Approval

Sensitive operations require explicit human approval before proceeding.

**Triggers**
- Writing to sensitive files (auth, config, `.env`, secrets)
- Update Mode modifying existing project code
- ResilienceManager escalation after max retries

**Flow**
1. Agent emits `hitl.approval_required` SSE event with action details and risk level
2. Inline `InlineApprovalCard` appears in WorkspaceChat — no page navigation required
3. Admin reviews the file list, optional note, then approves or rejects
4. Card locks to a read-only responded state; pipeline continues (approved) or cancels (rejected)

### 6. Dynamic MCP Tool Manager

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

### 7. Fusion Architect — Cross-Repository Analysis

The Fusion Architect Agent clones multiple repositories, analyses their codebases, and synthesises a unified architecture report combining the best patterns from each.

**Pipeline phases**

| Phase | Tool | Description |
|---|---|---|
| 1 — Clone | `clone_repo` | Clone any HTTPS/SSH Git URL into an isolated sandbox (GitHub, GitLab, Hugging Face, private servers) |
| 2 — Explore | `read_repo_file` / `glob_repo` / `grep_repo` / `analyze_ast` | Recursively read, search, and AST-analyse each codebase |
| 3 — Synthesise | LLM | Produce a fusion architecture report combining the best elements |
| 4 — Persist | `write_fusion_report` | Auto-promote the report to a reusable Markdown skill via ReflectionAgent |

- **Universal Git Fetcher**: platform-agnostic — works with any Git host. Auth tokens are embedded in the clone URL and scrubbed from logs.
- **Sandbox enforcement**: all file operations are confined to a single `repos_root` directory; path-traversal attempts raise `ValueError`.
- **AST analysis**: Python files get full `ast` structural analysis (imports, classes, functions, call sites); other languages fall back to regex.

### 8. Skill Dynamic Loading

Compound knowledge automatically promotes to discoverable, reusable skills.

- **SkillManifest** (`skills/manifest.yaml`): lightweight keyword index over all skill files. O(n) match at task arrival time.
- **SkillLoader**: on-demand Markdown skill file reader. Only loads matched files — no noise injected when nothing matches.
- **Compound knowledge → skill pipeline**: `ReflectionAgent` extracts lessons → promotes high-value patterns to `skills/{category}/` as Markdown files → updates the manifest → future CEO/Architect agents discover them via `SkillLoader.load_matched()`.
- Graceful degradation: missing manifest or skill files silently return empty string.

### 9. LLM-as-Judge Quality Gate

A strong model scores every Agent output on three dimensions before it reaches the user:

| Dimension | Score range | What it measures |
|---|---|---|
| **Hallucination** | 0.0–1.0 | Grounded in task/context vs. fabricated facts, non-existent APIs |
| **Accuracy** | 0.0–1.0 | Correct implementation matching requirements |
| **Relevance** | 0.0–1.0 | Directly addresses the task vs. off-topic |

Scores below threshold trigger a silent retry via the existing resilience loop. Integration point: called after QA passes in `ResilienceManager.run_task_loop()`.

### 10. Deep Context Compaction

Three-layer system to keep multi-turn tool-use sessions within context window limits:

| Layer | Module | Strategy |
|---|---|---|
| **1 — Tool Output Spill** | `tool_output_store.py` | Large tool results (>1200 chars) spill to disk; only head/tail preview stays in messages. Model can `recall_tool_output` if needed. |
| **2 — LLM Summarization** | `context_summarizer.py` | When message history reaches 85% of context window, early rounds are summarised by an LLM into a compact paragraph preserving key decisions and facts. |
| **3 — Task Handoff Compression** | `context_compressor.py` | On mid-task model switch, builds a compact briefing (~1200 chars) with goal, completed files, error summary, and continuation instruction. |

### 11. Security & Sandbox

**Sandbox Isolation** (`sandbox.py`)
- `ContentPreScreener.check_file()` screens files before execution
- `SandboxFactory` creates `ResourceLimitSandbox` (local) or `DockerSandbox` (containers)
- Direct `subprocess.run()` on generated code is forbidden

**Security Guardrails** (`guardrails.py`)
- `PromptGuard.check_input()` detects prompt injection patterns in task inputs
- `ContentModerator.screen_output()` screens LLM-generated file content for credentials and payloads
- `GuardRailViolation` is non-retryable — bypasses the resilience retry loop

### 12. FinOps Billing Engine

Per-tenant credit-based billing with thread-local side-channel:

1. `job_runner` loads tenant `credit_balance` and installs a `BillingContext` before pipeline start
2. After each LLM API call, the connector records a `LLMUsage` event
3. `ModelRouter` calls `check_credit()` before each API call — raises `InsufficientCreditError` (HTTP 402) if balance exhausted
4. On pipeline completion, `flush_context()` persists billing events and deducts from credit balance

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser  (Next.js 15 · App Router · Tailwind CSS)                  │
│                                                                      │
│  /knowledge  ──► KnowledgeGraph · WorkspaceChat · TaskCard          │
│                  InlineInterviewCard · InlineApprovalCard            │
│                  HistoryDrawer (session restore)                     │
│  /dashboard  ──► job history                                         │
│  /settings   ──► APIKeysTab · ModelsTab · MCPTab · ProfileTab        │
│  /console    ──► SystemStatusCards · TenantStatsPanel · TrendChart  │
│  /login /register /invite/[token] /pending   (auth routes)          │
│                                                                      │
│  SessionExpiredModal  (overlays on 401 without clearing state)       │
└───────────────────────┬─────────────────────────────────────────────┘
                        │  HTTPS + httpOnly cookies
                        │  /api/proxy/** (401→refresh→retry proxy)
┌──────────────────��────▼─────────────────────────────────────────────┐
│  FastAPI  (Uvicorn · async)                                          │
│                                                                      │
│  /auth          register · login · refresh · invite · me            │
│  /jobs          create · list · detail · cancel                      │
│  /jobs/{id}/stream   SSE stream (keepalive every 15 s)              │
│  /knowledge     chat · sessions · search · upload · ingest · graph  │
│  /approvals     HITL gate (approve / reject)                         │
│  /interview     CEO interview answer submission                      │
│  /settings      API keys · model config · CEO config (per-tenant)   │
│  /mcp           server CRUD + probe                                  │
│  /console       stats · trends (admin only)                          │
│                                                                      │
│  key_injector.py — bridges DB api_keys → os.environ at runtime      │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────────┐
│  Core Orchestrator  (pure Python · no framework)                     │
│                                                                      │
│  CEOAgent          (≥95% confidence clarifying interview)            │
│    └─► ArchitectAgent  (tool-use code generation)                    │
│          └─► Evaluator     (ast · pyflakes · subprocess sandbox)    │
│                └─► QAAgent     (code review)                         │
│                      └─► ReflectionAgent (lesson extraction)         │
│                                                                      │
│  FusionArchitect   (cross-repo clone → explore → synthesise → skill)│
│  SkillLoader       (manifest keyword match → on-demand Markdown)    │
│  Judge             (LLM-as-Judge: hallucination/accuracy/relevance) │
│  ModelRouter       (YAML routing · 30 s cache · ${VAR} interpolation)│
│  LLMConnector      (OpenAI / Anthropic adapter protocol · urllib)   │
│  ParallelExecutor  (Kahn BFS waves · ThreadPoolExecutor)            │
│  ResilienceManager (3-layer escalation · token budget guard)        │
│  HITLManager       (sensitive file gate · update-mode gate)         │
│  MCPManager        (hot-plug · per-tenant · urllib probe)           │
│  KnowledgeIngestion(PDF/URL → Markdown → concepts → graph → embed) │
│  KnowledgeRetriever(pre-task solution injection · keyword fallback) │
│  VectorStore       (pgvector upsert · Python cosine fallback)       │
│  SolutionStore     (YAML lesson library · workspace-scoped)         │
│  ToolOutputStore   (large tool result spill-to-disk + recall)       │
│  ContextSummarizer (LLM-powered conversation compaction at 85%)     │
│  ContextCompressor (compact briefing for mid-task model switch)     │
│  Sandbox           (ContentPreScreener + SandboxFactory)            │
│  Guardrails        (PromptGuard + ContentModerator)                 │
│  BillingEngine     (per-tenant credit limits · thread-local usage)  │
│  PIISanitizer      (composable redaction pipeline)                  │
└───────────────────────┬─────────────────────────────────────────────┘
                        │  asyncpg · SQLAlchemy 2.0 async
┌───────────────────────▼─────────────────────────────────────────────┐
│  PostgreSQL 16 + pgvector                                            │
│                                                                      │
│  tenants · users · refresh_tokens · workspaces                      │
│  jobs · job_events · checkpoints                                     │
│  solutions  (embedding 1536-dim via pgvector)                       │
│  knowledge_nodes · knowledge_edges  (graph tables)                  │
│  chat_sessions · chat_messages  (session persistence)               │
│  settings   PK: (tenant_id, key)                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Request flow — AI Workspace chat with `/task`**

1. User types `/task build <requirement>` in WorkspaceChat.
2. `callChat` sends `POST /knowledge/chat` with the current `session_id` (or null for new session).
3. Backend auto-creates or resumes the session; persists the user message.
4. A background `job_runner` thread starts the pipeline; a TaskCard is injected into the chat.
5. CEOAgent conducts a structured interview; each question emits `ceo.question` via SSE.
6. An `InlineInterviewCard` appears in the chat stream; user answers inline.
7. Architect decomposes work; `wave_schedule` computes parallel waves of tasks.
8. Each task runs concurrently; Evaluator + QA gate each output; ResilienceManager handles failures.
9. If a sensitive file write is required, an `InlineApprovalCard` appears for HITL confirmation.
10. ReflectionAgent extracts lessons; embeddings upserted to pgvector.
11. On completion a pipeline summary appears inline; the full session is persisted to DB.

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
> pipeline, knowledge graph, and semantic memory — is available without any API keys
> or credentials.
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
alembic upgrade head            # run all 11 schema migrations

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

1. **Settings UI** → API Keys tab — values are masked on read (last 4 chars only).
2. **`.env` file** — loaded at startup via `load_dotenv`.
3. **System environment variables** — useful for Docker and CI pipelines.

| Variable | Provider |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter (1 key → 300+ models) ⭐ recommended |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `OPENAI_API_KEY` | OpenAI GPT |
| `NVIDIA_API_KEY` + `NVIDIA_BASE_URL` | NVIDIA NIM |
| `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL` | DeepSeek V3 / R1 |
| `ZHIPU_API_KEY` + `ZHIPU_BASE_URL` | Zhipu GLM |
| `MOONSHOT_API_KEY` + `MOONSHOT_BASE_URL` | Moonshot / Kimi |
| `BRAVE_SEARCH_API_KEY` | Brave Search (web search; free tier 2,000 req/mo) |

> All keys are stored encrypted (Fernet) in the database when saved through the UI.
> They are injected into `os.environ` at request time by `api/key_injector.py` so
> the model router always uses the latest saved values without a restart.

### Model Routing (`models_config.yaml`)

```yaml
models:
  openrouter-claude-sonnet:
    provider: openai                              # OpenRouter uses the OpenAI protocol
    model_id: anthropic/claude-sonnet-4
    api_key_env: OPENROUTER_API_KEY
    base_url: https://openrouter.ai/api/v1
    max_tokens: 8192
    temperature: 0.7
    tier: standard

  my-local-model:
    provider: openai
    model_id: llama3                              # model name registered in Ollama
    api_key_env: LOCAL_API_KEY                    # any non-empty value for Ollama
    base_url_env: LOCAL_BASE_URL                  # http://localhost:11434/v1
    max_tokens: 8192
    temperature: 0.7

routes:
  - match: {}                                     # catch-all; first model with a valid key wins
    model: openrouter-claude-sonnet
  - match: {}
    model: my-local-model

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
├── core_orchestrator/         # Pure Python business logic (36 modules)
│   ├── ceo_agent.py           # Clarifying interview (≥95% confidence threshold)
│   ├── architect_agent.py     # Code generation via tool-use LLM
│   ├── fusion_architect_agent.py  # Cross-repo architecture analysis + synthesis
│   ├── git_fetcher.py         # Universal Git clone + 5 code analysis tools
│   ├── qa_agent.py            # Code review agent
│   ├── evaluator.py           # Sandbox: ast · pyflakes · subprocess
│   ├── reflection_agent.py    # Lesson extraction → SolutionStore → Skill promotion
│   ├── judge.py               # LLM-as-Judge (hallucination/accuracy/relevance)
│   ├── ce_orchestrator.py     # Pipeline coordinator (CEO→Architect→QA→Reflect)
│   ├── resilience_manager.py  # 3-layer escalation + token budget circuit breaker
│   ├── parallel_executor.py   # Kahn BFS wave scheduler + ThreadPoolExecutor
│   ├── retry_utils.py         # Exponential backoff (tenacity optional)
│   ├── model_router.py        # YAML-driven multi-provider routing (30 s TTL cache)
│   ├── llm_connector.py       # OpenAI / Anthropic adapter protocol + registry
│   ├── llm_gateway.py         # Translation gateway (auto-detects language)
│   ├── skill_loader.py        # SkillManifest keyword match + on-demand Markdown loader
│   ├── mcp_manager.py         # Hot-plug MCP server registry (urllib probe)
│   ├── knowledge_ingestion.py # PDF/URL → Markdown → concepts → graph → embeddings
│   ├── knowledge_manager.py   # Knowledge graph CRUD + semantic search
│   ├── knowledge_retriever.py # Pre-task solution injection (vector + keyword)
│   ├── vector_store.py        # pgvector upsert + Python cosine similarity fallback
│   ├── solution_store.py      # YAML lesson library (workspace-scoped)
│   ├── tool_output_store.py   # Large tool output spill-to-disk + recall
│   ├── context_compressor.py  # Compact briefing for mid-task model switch
│   ├── context_summarizer.py  # LLM-powered conversation compaction
│   ├── sandbox.py             # ContentPreScreener + SandboxFactory (Docker/local)
│   ├── guardrails.py          # PromptGuard + ContentModerator
│   ├── billing.py             # FinOps billing engine (per-tenant credit limits)
│   ├── pii_sanitizer.py       # Composable PII redaction pipeline
│   ├── web_browser.py         # Headless web page fetch + content extraction
│   ├── web_crawler.py         # URL → Markdown via markdownify
│   └── tests/                 # 1094 pytest tests across all modules
│
├── api/                       # FastAPI application (12 route modules)
│   ├── main.py                # App factory · lifespan hooks · CORS · crash recovery
│   ├── auth.py                # JWT creation/validation · DEV_MODE logic
│   ├── deps.py                # FastAPI Depends: CurrentUser · require_admin · require_owner
│   ├── job_runner.py          # Background pipeline thread (DB key injection + orchestrator)
│   ├── job_store.py           # In-memory job state + DB persistence bridge
│   ├── event_labels.py        # Human-readable SSE event label map (English)
│   ├── event_bridge.py        # SSE event routing (job → connected clients)
│   ├── hitl_manager.py        # HITL gate: sensitive file + update-mode approval
│   ├── interview_manager.py   # CEO interview answer bridge (agent ↔ API)
│   ├── key_injector.py        # DB api_keys → os.environ bridge (no restart needed)
│   ├── metrics.py             # Prometheus metrics registry + /metrics endpoint
│   ├── quota.py               # QuotaManager — per-tenant daily token budget
│   ├── rate_limit.py          # slowapi Limiter (10/min auth, 60/min jobs)
│   ├── settings_service.py    # Settings CRUD (PostgreSQL backed)
│   └── routes/                # auth · jobs · stream · approvals · interview
│                              # knowledge · settings · mcp · console · setup · admin
│
├── db/                        # Database layer
│   ├── models.py              # SQLAlchemy ORM (12+ tables)
│   ├── repository.py          # Async CRUD — all functions accept AsyncSession
│   ├── connection.py          # asyncpg engine · session factory · URL normalisation
│   └── migrations/            # Alembic revisions 001–011 (11 migrations)
│       ├── 001–005            # Core schema, embeddings, auth, workspaces, tenant scope
│       ├── 006–008            # Tenant quotas, billing tables, superadmin setup
│       └── 009–011            # Knowledge graph tables, vector resize, chat sessions
│
├── web/                       # Next.js 15 frontend
│   ├── app/
│   │   ├── knowledge/         # AI Workspace (primary interface)
│   │   │   ├── page.tsx       # Resizable dual-pane layout
│   │   │   └── components/
│   │   │       ├── WorkspaceChat.tsx     # Generative chat + task dispatch
│   │   │       ├── KnowledgeGraph.tsx    # D3.js interactive graph
│   │   │       ├── TaskCard.tsx          # Live pipeline progress (SSE)
│   │   │       ├── InlineInterviewCard.tsx  # CEO question card (inline)
│   │   │       ├── InlineApprovalCard.tsx   # HITL approval card (inline)
│   │   │       ├── HistoryDrawer.tsx     # Session history + restore
│   │   │       ├── KnowledgeChat.tsx     # Graph-grounded Q&A chat
│   │   │       └── UploadPanel.tsx       # Drag-and-drop ingestion
│   │   ├── dashboard/         # Job history list
│   │   ├── jobs/[id]/         # Job detail + approval actions
│   │   ├── settings/          # APIKeysTab · ModelsTab · MCPTab · CEOTab · ProfileTab
│   │   ├── console/           # Admin dashboard (stats · trends · tenant list)
│   │   ├── admin/             # User approval (super_admin only)
│   │   └── onboarding/        # First-run setup wizard
│   ├── components/
│   │   ├── Shell.tsx          # Auth-gated layout wrapper
│   │   ├── Sidebar.tsx        # Navigation + workspace switcher + theme toggle
│   │   ├── SessionExpiredModal.tsx  # Re-login overlay (no state loss)
│   │   ├── ApprovalModal.tsx  # Full-page HITL approval (jobs/[id] route)
│   │   ├── InterviewPanel.tsx # Full-page CEO interview (jobs/[id] route)
│   │   ├── Timeline.tsx       # SSE event log timeline
│   │   └── generative/        # EventCard · FileCard · QAVerdict
│   ├── lib/
│   │   ├── auth/
│   │   │   ├── context.tsx    # AuthProvider + session-expired event listener
│   │   │   ├── client.ts      # API client (login · logout · register · refresh)
│   │   │   └── sessionGuard.ts  # window.fetch monkey-patch → aegis:session-expired events
│   │   ├── i18n/              # useT() hook · en.ts · zh.ts (dual-language UI)
│   │   ├── eventLabels.ts     # Frontend SSE event label map + event sets
│   │   └── theme/             # Dark/light theme context
│   └── hooks/
│       └── useApproval.ts     # HITL approval polling hook
│
├── skills/                    # Reusable Markdown skill files (auto-promoted from knowledge)
│   ├── manifest.yaml          # Keyword index for SkillLoader fast matching
│   ├── python/                # Python / FastAPI / architecture skills
│   ├── frontend/              # React / Next.js skills
│   ├── database/              # SQL / migration skills
│   ├── devops/                # Docker / CI / deployment skills
│   └── architecture/          # Cross-repo fusion architecture reports
│
├── workspaces/                # Generated code artifacts (volume-mounted · git-ignored)
├── knowledge_base/            # Curated lesson library (pre-seeded)
├── models_config.yaml         # LLM routing configuration (18+ providers pre-configured)
├── docker-compose.yml         # Production stack (postgres · backend · frontend)
├── docker-compose.override.yml # Local dev overrides (hot-reload)
├── Dockerfile                 # Backend multi-stage image (non-root uid 1000)
├── .env.example               # Environment variable template with all providers
├── ARCHITECTURE.md            # Full system design reference
├── AGENTS.md                  # Agent operating manual
└── CHANGELOG.md               # Version history
```

---

## Development

### Running Tests

```bash
pytest                           # all 1094 tests
pytest core_orchestrator/tests/  # orchestrator unit tests only
pytest -k test_resilience        # filter by name
pytest -k test_fusion            # fusion architect + git fetcher tests
pytest -k test_skill             # skill loader tests
pytest -k test_judge             # LLM-as-Judge tests
pytest --cov=core_orchestrator --cov-report=term-missing  # coverage report
```

### Database Migrations

```bash
alembic upgrade head                                  # apply all 11 pending migrations
alembic revision --autogenerate -m "describe change"  # generate a new revision
alembic downgrade -1                                  # roll back one revision
alembic current                                       # show current revision
```

### Adding a New LLM Provider

1. Add an entry under `models:` in `models_config.yaml` with `provider: openai`. All OpenAI-compatible APIs work without any code changes.
2. If the provider requires a non-standard auth scheme, implement `LLMConnector` in `core_orchestrator/llm_connector.py` and register it with `register_connector("my-provider", MyConnector())`.
3. Add the API key env var name to `.env.example`, the `_DB_KEY_TO_ENV` mapping in `api/key_injector.py`, and the onboarding provider catalogue (`web/app/onboarding/providers.ts`).

### SSE Event Reference

| Event type | Key payload fields | Description |
|---|---|---|
| `pipeline.start` | `job_id` | Pipeline begins |
| `ceo.interviewing` | — | CEO clarifying requirements |
| `ceo.question` | `question` | CEO asks user a question (triggers InlineInterviewCard) |
| `ceo.plan_created` | `task_count` | Development plan ready |
| `architect.solving` | `task_id` | Architect writing code for a task |
| `architect.file_written` | `filepath` | File committed to workspace |
| `hitl.approval_required` | `reason`, `files`, `risk` | Human approval needed (triggers InlineApprovalCard) |
| `hitl.approved` / `hitl.rejected` | `note` | HITL decision received |
| `evaluator.pass` / `evaluator.fail` | — | Sandbox validation result |
| `qa.pass` / `qa.fail` | — | Code review result |
| `pipeline.complete` | `artifacts` | All tasks finished |
| `pipeline.error` | `error` | Unrecoverable failure |
| `pipeline.rejected` | — | User cancelled |

---

## Contributing

**Zero blast radius** — every change must leave the system at least as functional as before.

- **Test-first**: Add or update tests before touching production code. The 1094-test suite is the regression gate; all tests must pass before any merge.
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
