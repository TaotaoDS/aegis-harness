# AegisHarness

> **v0.0.2** — Multi-Agent Code Generation & Orchestration Platform  
> 598 tests passing · 17-provider BYOM · i18n (zh/en) · PostgreSQL + pgvector · Kahn BFS Wave Scheduler · SSE Streaming Chat UI · MCP Dynamic Tool Manager

English | [中文](./README.zh-CN.md)

---

## What is AegisHarness?

AegisHarness is a production-grade autonomous coding platform. You describe a software requirement; AegisHarness conducts a structured requirements interview, decomposes the work into tasks, generates and verifies code through a multi-agent pipeline, and learns from every mistake — building a growing semantic memory that makes every subsequent project smarter.

**Core loop**:
```
CEO Interview → Wave-Parallel Execution → Reflection → Semantic Memory → Next Run
```

---

## Quick Start

### Option A — Docker (recommended)

```bash
git clone <repo>
cd enterprise-harness
cp .env.docker .env       # fill in your API keys (see .env.example)
docker compose up --build
```

| Service | URL |
|---|---|
| Web Console | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

### Option B — Local Development

**Prerequisites**: Python 3.12+, Node 20+

```bash
# Backend
pip install -r requirements.txt
cp .env.example .env      # fill in API keys
uvicorn api.main:app --reload --port 8000

# Frontend (separate terminal)
cd web
npm install
npm run dev
```

Without `DATABASE_URL` the system runs in **file-only mode** — full functionality except DB persistence and semantic search.

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────┐
│                  Web Console (Next.js 14)            │
│  /chat  /jobs  /settings (Profile/CEO/Keys/MCP)     │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────┐
│           AegisHarness API  v0.0.1  (FastAPI)        │
│  /jobs  /events (SSE)  /settings  /mcp/servers      │
│  Lifespan: DB init + crash recovery                 │
└──────────────────────┬──────────────────────────────┘
                       │ Python async
┌──────────────────────▼──────────────────────────────┐
│              Core Orchestrator (pure Python)         │
│                                                     │
│  CEOAgent ──► ResilienceManager ──► ReflectionAgent │
│                │                                    │
│                ├─ ParallelExecutor (Kahn BFS waves) │
│                ├─ RetryUtils (exponential backoff)  │
│                ├─ ArchitectAgent (tool-use LLM)     │
│                ├─ Evaluator (sandbox checks)        │
│                └─ QAAgent (code review)             │
│                                                     │
│  SolutionStore ◄──────────────── VectorStore        │
│  (YAML lessons)   semantic search  (OpenAI embeds)  │
│                                                     │
│  MCPManager  UserProfile  PIISanitizer  WorkspaceManager │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│         PostgreSQL 16 + pgvector  (port 5432)        │
│  jobs · events · checkpoints · solutions · settings  │
│  solutions.embedding  JSON float[1536]               │
└─────────────────────────────────────────────────────┘
```

For the full design reference see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## What's New in v0.0.2

### BYOM — Bring Your Own Model (17 providers)

The first-run onboarding wizard now supports any LLM provider through a
two-panel UI: select a provider on the left, fill in **API Key**, **Base URL**,
and **Model Identifier** on the right. No dropdown menus — enter any model ID
exactly as it appears in the provider's documentation.

| Group | Providers |
|---|---|
| **Global** | Anthropic · OpenAI · Google Gemini · Mistral AI · Groq · xAI (Grok) · Together AI |
| **China** | DeepSeek · Alibaba Qwen · 智谱 GLM · Moonshot/Kimi · 百度文心 · MiniMax · 零一万物 · 字节豆包 |
| **Local** | Ollama · vLLM · Custom (any OpenAI-compatible endpoint) |

For local providers (`Ollama`, `vLLM`) the API Key field is hidden — only the
endpoint URL and model name are required.

### i18n — Automatic Language Detection

The entire web console now switches between **Chinese (Simplified)** and
**English** based on `navigator.language`, with a manual 中文 / EN toggle in
the top navigation bar.

### PII Sanitisation Middleware

```python
from core_orchestrator import default_pipeline
safe = default_pipeline()
safe("Reach me at bob@corp.com or 138-0000-0000")
# → "Reach me at [EMAIL_REDACTED] or [PHONE_REDACTED]"
```

Composable pipeline covering email, phone (CN + US + international), Chinese ID
cards, and credit-card numbers. 30 tests, all passing.

---

## Core Infrastructure (v0.0.1)

### 1. PostgreSQL + pgvector Semantic Search

AegisHarness persists all state in PostgreSQL 16. The `solutions` table stores lessons learned across projects, including a 1536-dimensional OpenAI embedding for each lesson.

```python
# After a task succeeds:
store.save({"problem": "...", "solution": "...", "type": "error_fix"})
await vs.upsert(solution_id, problem + " " + solution)   # embed + store

# Before planning the next task:
context = store.semantic_search("async database pooling")  # top-5 by cosine
```

- **Embedding model**: `text-embedding-3-small` (1536 dims)
- **Similarity**: pure-Python cosine — no pgvector PG extension required
- **Graceful degradation**: silent no-op when `OPENAI_API_KEY` or `DATABASE_URL` is absent

Schema managed by Alembic:
```bash
alembic upgrade head   # applies 001_initial_schema + 002_add_embedding_column
```

### 2. Kahn BFS Wave Scheduler + ThreadPoolExecutor

Tasks declare dependencies in their plan files:
```markdown
- **Depends on:** task_1, task_2
```

`wave_schedule()` uses Kahn's BFS to group independent tasks into concurrent waves:
```
depends_on = {"task_1": [], "task_2": ["task_1"], "task_3": ["task_1"], "task_4": ["task_2", "task_3"]}
waves      = [["task_1"], ["task_2", "task_3"], ["task_4"]]
```

`ParallelExecutor(workers=N)` submits each wave to a `ThreadPoolExecutor`, waits for all futures before advancing. Default `workers=1` preserves sequential behaviour for backward compatibility.

### 3. SSE Streaming Chat UI

`/chat` provides a real-time chat interface over Server-Sent Events:

- **Phase state machine**: `idle → creating → streaming → done | error`
- CEO interview questions render as chat bubbles with **clickable option buttons** for non-technical users
- System events (plan ready, task pass/fail, execution complete) render as inline status pills
- Auto-scroll, auto-resize input, keyboard shortcuts (Enter submit / Shift+Enter newline)

### 4. MCP Dynamic Tool Manager

Register any MCP-compatible tool server without redeploying:

```bash
# Via API
curl -X POST http://localhost:8000/mcp/servers \
  -d '{"name": "my-tools", "url": "http://localhost:9000"}'

# Probe connectivity + discover tools
curl -X POST http://localhost:8000/mcp/servers/{id}/probe
```

Or use **Settings → 🔧 MCP Tool** in the web console. Registrations persist across restarts.

### 5. 3-Layer Resilience + Exponential Backoff

Every LLM call retries automatically on transient errors (429, 5xx, connection timeout):
```
Attempt 1 → fail (RateLimitError) → wait 1s
Attempt 2 → fail (503)            → wait 2s
Attempt 3 → fail                  → wait 4s
Attempt 4 → success
```

The Architect → QA loop has three escalation layers:
1. **Context Reset** — inject feedback, retry same model
2. **Model Escalation** — switch to higher-tier model
3. **Human Escalation** — write escalation file, notify operator

---

## Configuration

### API Keys (`.env`)

```bash
# ── Global providers (at least one required) ──────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
GOOGLE_API_KEY=AIzaSy...
MISTRAL_API_KEY=...
GROQ_API_KEY=gsk_...
XAI_API_KEY=xai-...
TOGETHER_API_KEY=...

# ── China providers ────────────────────────────────────────────────────────
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...        # Alibaba Qwen / 通义千问
ZHIPUAI_API_KEY=...             # 智谱 GLM
MOONSHOT_API_KEY=sk-...         # Moonshot / Kimi
BAIDU_API_KEY=...               # 百度文心 ERNIE
MINIMAX_API_KEY=...
YI_API_KEY=...                  # 零一万物
ARK_API_KEY=...                 # 字节豆包 Doubao

# ── Local providers: no key needed — configure Base URL in the wizard ──────
# Ollama default: http://localhost:11434/v1
# vLLM  default: http://localhost:8000/v1

# ── PostgreSQL (optional — omit for file-only mode) ───────────────────────
DATABASE_URL=postgresql://harness:harness_secret@localhost:5432/harness
```

> **Tip**: You can configure all of the above through the first-run wizard
> at `/onboarding` — keys are stored only in your local database and are
> never sent to any third-party server.

### Model Routing (`models_config.yaml`)

```yaml
# AegisHarness — Model Configuration
roles:
  ceo:       claude-3-5-sonnet-20241022
  architect: gpt-4o
  qa:        gpt-4o-mini
  escalated: claude-3-5-opus-20241022

execution:
  max_retries: 3
  parallel_workers: 1
```

### Settings via Web Console

All settings persist to the database — no restart required:

| Tab | Purpose |
|---|---|
| 👤 User Profile | Name, role, technical level — adapts CEO interview style |
| 🤖 CEO Config | Agent name + custom system prompt prefix |
| 🔑 API Keys | Provider API keys (masked in UI) |
| ⚡ Models | Default model selection |
| 🔧 MCP Tools | Register / probe / remove MCP tool servers |

---

## Project Structure

```
enterprise-harness/           ← repo root (project: AegisHarness v0.0.2)
├── core_orchestrator/        ← business logic (pure Python)
│   ├── ceo_agent.py          ← requirements interview + planning
│   ├── resilience_manager.py ← 3-layer escalation + wave execution
│   ├── parallel_executor.py  ← Kahn BFS + ThreadPoolExecutor
│   ├── retry_utils.py        ← exponential backoff (tenacity)
│   ├── pii_sanitizer.py      ← composable PII redaction middleware (NEW)
│   ├── vector_store.py       ← OpenAI embeddings + cosine search
│   ├── solution_store.py     ← YAML lessons + semantic bridge
│   ├── mcp_manager.py        ← MCP server registry
│   └── tests/                ← 598 pytest tests
├── api/                      ← FastAPI backend
│   ├── main.py               ← app factory + lifespan + crash recovery
│   └── routes/               ← jobs, stream, settings, mcp, approvals
├── db/                       ← database layer
│   ├── models.py             ← SQLAlchemy ORM (5 tables)
│   ├── repository.py         ← async CRUD
│   └── migrations/           ← Alembic revisions
├── web/                      ← Next.js 14 frontend
│   ├── lib/i18n/             ← zh.ts + en.ts + React context (NEW)
│   ├── components/
│   │   ├── Nav.tsx           ← top nav with zh/en toggle (NEW)
│   │   └── Providers.tsx     ← LocaleProvider client wrapper (NEW)
│   └── app/
│       ├── chat/             ← SSE streaming chat UI
│       ├── onboarding/
│       │   ├── providers.ts  ← 17-provider catalogue + types (NEW)
│       │   └── components/   ← StepWelcome/APIKeys/Database/Model/Done
│       └── settings/         ← 5-tab settings panel
├── Dockerfile                ← backend multi-stage image
├── docker-compose.yml        ← postgres + backend + frontend
├── ARCHITECTURE.md           ← full system design reference
└── AGENTS.md                 ← agent operating manual
```

---

## Development

### Running Tests

```bash
# Full suite — must all pass before any commit
python -m pytest core_orchestrator/tests/ -v

# Single module
python -m pytest core_orchestrator/tests/test_resilience_manager.py -v

# Coverage report
python -m pytest core_orchestrator/tests/ --cov=core_orchestrator --cov-report=term-missing
```

**Current**: **598 tests, all passing** (AegisHarness v0.0.2).

### Database Migrations

```bash
alembic upgrade head              # apply all pending migrations
alembic revision -m "add_column"  # create a new migration
alembic current                   # check current revision
```

### CLI Usage

```bash
# Run full pipeline from terminal
python main.py --workspace my_project

# Update mode (modify existing deliverables)
python main.py --workspace my_project --update "Add input validation to all endpoints"

# Start fresh (discard checkpoint)
python main.py --workspace my_project --reset
```

---

## Contributing

1. **Zero Blast Radius**: all 598 tests must pass after any change.
2. **Write tests first**: add tests before implementation.
3. **Graceful degradation**: every new integration must be a no-op when its dependency is unavailable.
4. **Read `ARCHITECTURE.md`** before making structural changes.
5. **Read `AGENTS.md`** for the agent operating manual and common pitfalls.

---

## License

MIT
