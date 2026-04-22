# Enterprise Harness

Enterprise-grade multi-agent orchestration harness. A CEO agent interviews you to clarify requirements, decomposes work into tasks, and delegates to Architect, QA, Resilience Manager, and CE Orchestrator agents via a shared file-based workspace.

Supports **greenfield builds** and **incremental updates** to existing projects.

## Architecture

```
User (terminal)
  |
  v
main.py  ──>  CEO Agent (reverse interview + plan + delegate)
                |
                v
           Shared Workspace (file-based)
                |
        ┌───────┼───────────────┐
        v       v               v
   Architect  Evaluator    Resilience Manager
  (Tool Use   (sandbox     (3-layer escalation
  write_file)  verify)      + knowledge capture)
        │       │               │
        └── QA ─┘               v
          (review)        Knowledge Manager
                          (global_knowledge_base.md)
                                │
                                v
                         CE Orchestrator
                      (5 sub-agent post-mortem)
```

### Model-Agnostic Layer

Agents never touch model APIs directly. The abstraction stack is:

```
Agent → LLMGateway(llm=Callable) → ModelRouter.as_llm() → LLMConnector.call()
                                                                 |
                                          ┌──────────────────────┼──────────────────┐
                                          v                      v                  v
                                   OpenAIConnector       AnthropicConnector    (custom)
                                   (OpenAI, NVIDIA NIM,  (Claude)              register_connector()
                                    DeepSeek, Zhipu,
                                    Kimi, Ollama, vLLM…)
```

Any provider with an OpenAI-compatible API works out of the box. Two config patterns:

| Pattern | YAML example | When to use |
|---------|-------------|-------------|
| **A** — env-var indirection | `api_key_env: NVIDIA_API_KEY` | Keeps key names explicit |
| **B** — `${VAR}` interpolation | `api_key: ${NVIDIA_API_KEY}` | Cleaner for third-party endpoints |

Both patterns can be freely mixed within the same `models_config.yaml`.

### Agent Pipeline

| Agent | Role |
|-------|------|
| **CEO** | Reverse-interviews the user, generates a plan, delegates tasks. Communicates in the user's language; produces English-only internal artifacts. In Update Mode, reads existing deliverables and generates targeted modification tasks instead of rebuilding from scratch. |
| **Architect** | Code producer. Uses native **Tool Use (Function Calling)** — the LLM calls `write_file(filepath, content)` to write files. In Update Mode also gets `read_file` to inspect existing code before modifying it. |
| **Evaluator** | Sandbox verifier. Runs between Architect and QA: validates file existence, Python/JS syntax, HTML structure. Failures feed back to Architect. |
| **QA** | Binary verdict reviewer. Pass → `approved/`, Fail → `feedback/`. Never modifies code. |
| **Resilience Manager** | Wraps Architect → Evaluator → QA loop with 3-layer escalation and knowledge capture. |
| **Knowledge Manager** | Compound learning. Auto-captures bug/fix/guide after retries; injects lessons into future Architect prompts. |
| **CE Orchestrator** | Post-mortem analysis engine. Runs 5 independent sub-agents and writes structured post-mortem docs. |

### Key Design Decisions

- **Tool Use (Function Calling)**: Architect uses native LLM tool invocation instead of brittle regex text parsing. `write_file` / `read_file` are registered as first-class tools.
- **Model-agnostic**: `LLMConnector` Protocol decouples agents from providers. OpenAI-compatible APIs work via `base_url` or `base_url_env`; extensible via `register_connector()`.
- **`${VAR}` YAML interpolation**: Environment variable placeholders in `models_config.yaml` are resolved at startup, making third-party API configs readable and self-documenting.
- **English-only internals**: All workspace artifacts are strictly English to save tokens and improve model reasoning.
- **PII sanitization**: All user input passes through a regex-based sanitizer before reaching any LLM.
- **Token overflow management**: 2-stage compression prevents infinite context growth.
- **File-based workspace**: Double-layer path traversal protection. No database required.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# Edit .env — fill in your API keys (see Configuration below)

# 3. Build a new project
python main.py

# 4. Update an existing project (Update Mode)
python main.py --workspace my_project -u "Fix the login button color to blue"
```

## Configuration

### 1. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in at least **one** provider key:

```env
# Option A: Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-your-key

# Option B: OpenAI
OPENAI_API_KEY=sk-your-key

# Option C: NVIDIA NIM (free 1000-call quota, hundreds of open-source models)
NVIDIA_API_KEY=nvapi-your-key

# Option D: DeepSeek, Zhipu, Kimi, Ollama, vLLM — any OpenAI-compatible endpoint
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

**Important**: Never commit `.env` to version control (already in `.gitignore`).

### 2. Model routing (`models_config.yaml`)

The config file supports **two equivalent patterns** for specifying API credentials:

**Pattern A — env-var name indirection (original):**
```yaml
models:
  claude-sonnet:
    provider: anthropic
    model_id: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY       # stores the env var *name*
    max_tokens: 8192
```

**Pattern B — `${VAR}` inline interpolation (recommended for third-party APIs):**
```yaml
models:
  nvidia-llama:
    provider: openai                     # OpenAI-compatible endpoint
    model_id: meta/llama-3.3-70b-instruct
    api_key: ${NVIDIA_API_KEY}           # resolved from .env at startup
    base_url: https://integrate.api.nvidia.com/v1
    max_tokens: 4096
    temperature: 0.2
```

Route configuration:
```yaml
routes:
  - match: { customer: "enterprise", task: "reasoning" }
    model: nvidia-llama
  - match: {}                            # fallback (required)
    model: claude-sonnet
```

### 3. Adding NVIDIA NIM

1. Get a free API key at [build.nvidia.com](https://build.nvidia.com) (1000 free calls)
2. Add to `.env`:
   ```env
   NVIDIA_API_KEY=nvapi-your-key
   ```
3. Uncomment the `nvidia-llama` block in `models_config.yaml` (Pattern B)
4. Add a route pointing to it

NVIDIA NIM hosts hundreds of models (Llama, Mistral, Mixtral, Qwen, etc.) — change `model_id` to any model listed on their catalog.

### 4. Adding any other OpenAI-compatible provider

Same as NVIDIA — just set the `base_url` to the provider's endpoint:

| Provider | `base_url` |
|----------|-----------|
| DeepSeek | `https://api.deepseek.com/v1` |
| Zhipu/GLM | `https://open.bigmodel.cn/api/paas/v4` |
| Kimi/Moonshot | `https://api.moonshot.cn/v1` |
| Ollama (local) | `http://localhost:11434/v1` |
| vLLM (local) | `http://localhost:8000/v1` |

### 5. Adding a non-OpenAI-compatible provider (e.g., Gemini)

```python
from core_orchestrator import register_connector

class GeminiConnector:
    def call(self, *, model_id, api_key, text, max_tokens, temperature, base_url=None):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_id)
        return model.generate_content(text).text

register_connector("gemini", GeminiConnector())
```

Then add `provider: gemini` in `models_config.yaml`.

## Usage

### Greenfield build (new project)

```bash
python main.py
python main.py --workspace my_project   # custom workspace ID
python main.py --reset                  # discard checkpoint, start fresh
```

**What happens:**
1. Enter your requirement (any language — Chinese, English, etc.)
2. CEO asks clarifying questions
3. CEO generates an English-only plan and delegates tasks to `tasks/`
4. Architect uses Tool Use to write code files to `deliverables/`
5. Evaluator validates syntax; QA reviews; failures loop back with feedback
6. CE Orchestrator writes post-mortem docs to `docs/solutions/`

### Update Mode (iterate on existing project)

```bash
python main.py --workspace my_project --update "Fix the submit button color to blue"
python main.py -w my_project -u "Add dark mode support"
```

**What happens:**
1. CEO reads `deliverables/` and generates 1–5 targeted modification tasks
2. Architect reads existing files via `read_file`, then calls `write_file` for surgical changes
3. Only the new tasks are executed — existing approved work is untouched

### Checkpoint / Resume

The pipeline saves progress after each stage to `workspaces/<id>/checkpoint.json`. Re-run to resume:

```bash
python main.py                  # resumes automatically
python main.py --reset          # discard checkpoint, start fresh
```

Stages: `interviewed → delegated → executed → postmortem`

### Example session

```
$ python main.py

============================================================
  Enterprise Harness — Multi-Agent Orchestrator
============================================================
Workspace: default

Enter your requirement (what do you want to build?):
> Build a REST API for user management with OAuth2 authentication

[CEO] What are the expected user roles and permission levels?
> Admin and regular users. Admins manage all users; users update their own profile.

[CEO] Interview complete. Generating plan...
[CEO] Plan created with 4 task(s).
  - [high] task_1: Design database schema
  - [high] task_2: Implement OAuth2 authentication
  - [high] task_3: Build REST endpoints
  - [medium] task_4: Write integration tests

[Execution] Running Architect + Evaluator + QA pipeline...
  [PASS] task_1 (attempts: 1) -> artifacts/task_1_solution.md
  [PASS] task_2 (attempts: 2) -> artifacts/task_2_solution.md
  ...
```

```
$ python main.py -u "Add rate limiting to the login endpoint"

[Update Mode] Requirement: Add rate limiting to the login endpoint

[Update] Analyzing existing codebase and planning changes...
[Update] Generated 1 update task(s):
  - [high] task_5: Add rate limiting (files: auth.py, config.py)

[Execution] Running Architect + Evaluator + QA on 1 update task(s)...
  [PASS] task_5 (attempts: 1) -> artifacts/task_5_solution.md
```

## Running Tests

```bash
# Full test suite (no API keys needed — all mocked)
python3 -m pytest core_orchestrator/tests/ -v

# Individual modules
python3 -m pytest core_orchestrator/tests/test_model_router.py -v    # routing + interpolation
python3 -m pytest core_orchestrator/tests/test_architect_agent.py -v # Tool Use protocol
python3 -m pytest core_orchestrator/tests/test_update_mode.py -v     # Update Mode
python3 -m pytest core_orchestrator/tests/test_main.py -v            # CLI pipeline
```

All 428 tests use mock LLMs and require no API keys or network access.

## Project Structure

```
enterprise-harness/
├── main.py                              # CLI entry point (--update / -u flag)
├── models_config.yaml                   # Model & route definitions (edit this!)
├── requirements.txt                     # Python dependencies
├── .env.example                         # API key + URL template (copy to .env)
├── CHANGELOG.md                         # Version history
├── README.md                            # This file
├── core_orchestrator/
│   ├── __init__.py                      # Public API exports
│   ├── llm_connector.py                 # LLMConnector Protocol + OpenAI/Anthropic
│   ├── pii_sanitizer.py                 # PII regex sanitizer middleware
│   ├── llm_gateway.py                   # LLM gateway + token overflow management
│   ├── model_router.py                  # YAML config + ${VAR} interpolation + routing
│   ├── workspace_manager.py             # File-based shared workspace
│   ├── ceo_agent.py                     # CEO state machine (build + update modes)
│   ├── architect_agent.py               # Architect — Tool Use write_file/read_file
│   ├── evaluator.py                     # Sandbox verifier (syntax + execution)
│   ├── knowledge_manager.py             # Compound learning (global knowledge base)
│   ├── qa_agent.py                      # QA evaluator (binary verdict)
│   ├── resilience_manager.py            # 3-layer escalation + evaluator + knowledge
│   ├── ce_orchestrator.py               # Post-mortem analysis (5 sub-agents)
│   └── tests/                           # 428 tests, all mock-based
│       ├── test_llm_connector.py
│       ├── test_model_router.py         # incl. ${VAR} interpolation + NVIDIA NIM
│       ├── test_pii_sanitizer.py
│       ├── test_llm_gateway.py
│       ├── test_workspace_manager.py
│       ├── test_ceo_agent.py
│       ├── test_architect_agent.py      # Tool Use protocol
│       ├── test_update_mode.py          # Update Mode (CEO + Architect + CLI)
│       ├── test_qa_agent.py
│       ├── test_resilience_manager.py
│       ├── test_ce_orchestrator.py
│       ├── test_translation_gateway.py
│       ├── test_main.py
│       ├── test_checkpoint.py
│       ├── test_event_bus.py
│       └── test_json_parser.py
├── knowledge_base/                      # Design decision docs
└── workspaces/                          # Runtime workspace (gitignored)
```
