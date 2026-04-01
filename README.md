# Enterprise Harness

Enterprise-grade multi-agent orchestration harness. A CEO agent interviews you to clarify requirements, decomposes work into tasks, and delegates to Architect, QA, Resilience Manager, and CE Orchestrator agents via a shared file-based workspace.

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
   (===FILE   (sandbox     (3-layer escalation
    blocks)    verify)      + knowledge capture)
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
                                   OpenAIConnector       AnthropicConnector    (your custom)
                                   (OpenAI, DeepSeek,    (Claude)              register_connector()
                                    Zhipu, Kimi, Ollama,
                                    vLLM, etc.)
```

Any provider with an OpenAI-compatible API works out of the box — just set `base_url_env` in config.

### Agent Pipeline

| Agent | Role |
|-------|------|
| **CEO** | Reverse-interviews the user, generates a plan, delegates tasks. Acts as a translation gateway: communicates in the user's language but produces English-only internal artifacts. |
| **Architect** | Code producer. Outputs `===FILE: path===` blocks; agent parses them and writes physical files to `src/`. Reads knowledge base before each task. |
| **Evaluator** | Sandbox verifier. Runs between Architect and QA: validates file existence, Python/JS syntax, HTML structure. Failures feed back to Architect. |
| **QA** | Binary verdict reviewer. Pass -> `approved/`, Fail -> `feedback/`. Never modifies code. |
| **Resilience Manager** | Wraps Architect → Evaluator → QA loop with 3-layer escalation and knowledge capture. Reads `max_retries` from config. |
| **Knowledge Manager** | Compound learning. Auto-captures bug/fix/guide after retries; injects lessons into future Architect prompts. |
| **CE Orchestrator** | Post-mortem analysis engine. Runs 5 independent sub-agents and writes structured post-mortem docs. |

### Key Design Decisions

- **Model-agnostic**: `LLMConnector` Protocol decouples agents from providers. OpenAI-compatible APIs (DeepSeek, Zhipu, Kimi, Ollama, vLLM) work via `base_url_env`. Extensible via `register_connector()`.
- **English-only internals**: All workspace artifacts are strictly English to save tokens and improve model reasoning.
- **PII sanitization**: All user input passes through a regex-based sanitizer before reaching any LLM.
- **Token overflow management**: 2-stage compression prevents infinite context growth.
- **File-based workspace**: Double-layer path traversal protection. No database required.

## Quick Start

Three steps to run:

```bash
# 1. Install dependencies
pip install tiktoken pyyaml python-dotenv openai anthropic

# 2. Configure API keys
cp .env.example .env
# Edit .env — fill in your API keys (see below)

# 3. Run
python main.py
```

## Configuration

### 1. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in your keys. At minimum, you need **one** of the following:

```env
# Option A: Use Anthropic (default model)
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Option B: Use OpenAI
OPENAI_API_KEY=sk-your-key-here

# Option C: Use a free/open-source model (DeepSeek, Zhipu, Kimi, etc.)
# These use OpenAI-compatible APIs — just set the key and URL:
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

**Important**: Never commit `.env` to version control. It is already in `.gitignore`.

### 2. Model routing

The model configuration is in project root `models_config.yaml`:

```yaml
models:
  claude-sonnet:
    provider: anthropic                    # or "openai" for OpenAI-compatible
    model_id: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY         # env var name, never the actual key
    max_tokens: 4096
    tier: standard
    # temperature: 0.7                     # optional, default 0.7
    # base_url_env: CUSTOM_BASE_URL        # optional, for custom endpoints

routes:
  - match: { customer: "enterprise", task: "reasoning" }
    model: claude-opus
  - match: {}                              # fallback
    model: claude-sonnet
```

Default routes:

| Context | Model |
|---------|-------|
| enterprise + reasoning | claude-opus |
| enterprise | claude-sonnet |
| reasoning | gpt-4o |
| fallback (any) | claude-sonnet |

### 3. Adding a new provider (e.g., DeepSeek)

1. Uncomment the model block in project root `models_config.yaml`:
   ```yaml
   deepseek-chat:
     provider: openai           # OpenAI-compatible API
     model_id: deepseek-chat
     api_key_env: DEEPSEEK_API_KEY
     base_url_env: DEEPSEEK_BASE_URL
     max_tokens: 4096
     temperature: 0.3
     tier: standard
   ```

2. Add the env vars to `.env`:
   ```env
   DEEPSEEK_API_KEY=sk-your-key
   DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
   ```

3. Update a route to use it:
   ```yaml
   routes:
     - match: {}
       model: deepseek-chat
   ```

The same pattern works for Zhipu (GLM), Kimi (Moonshot), Ollama, vLLM, or any OpenAI-compatible endpoint.

### 4. Adding a non-OpenAI-compatible provider (e.g., Gemini)

```python
from core_orchestrator import register_connector

class GeminiConnector:
    def call(self, *, model_id, api_key, text, max_tokens, temperature, base_url=None):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_id)
        resp = model.generate_content(text)
        return resp.text

register_connector("gemini", GeminiConnector())
```

Then add `provider: gemini` in your YAML config.

## Usage

### Run the CLI

```bash
python main.py
```

With a custom workspace:

```bash
python main.py --workspace my_project
```

### What happens

1. You enter a requirement in your native language (Chinese, English, etc.)
2. The CEO agent asks clarifying questions (in your language)
3. Once satisfied, the CEO generates an English-only plan
4. Tasks are delegated to individual files in `workspaces/<id>/tasks/`

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
> Admin and regular users. Admin can manage all users, regular users can only update their own profile.

[CEO] What database do you plan to use?
> PostgreSQL

[CEO] Interview complete. Generating plan...
[CEO] Plan created with 4 task(s).
  - [high] task_1: Design database schema
  - [high] task_2: Implement OAuth2 authentication
  - [high] task_3: Build REST endpoints
  - [medium] task_4: Write integration tests

Delegating tasks to workspace...
[CEO] Delegated 4 task file(s):
  -> tasks/task_1.md
  -> tasks/task_2.md
  -> tasks/task_3.md
  -> tasks/task_4.md

Done. Task files written to workspaces/default/tasks/
```

## Checkpoint / Resume

The pipeline saves progress after each stage to `workspaces/<id>/checkpoint.json`.
If interrupted, re-run the same command to resume from where you left off:

```bash
python main.py                  # resumes automatically
python main.py --reset          # discard checkpoint, start fresh
```

Stages: `interviewed → delegated → executed → postmortem`

## Running Tests

```bash
# Full test suite (no API keys needed)
python -m pytest core_orchestrator/tests/ -v

# Individual modules
python -m pytest core_orchestrator/tests/test_llm_connector.py -v
python -m pytest core_orchestrator/tests/test_model_router.py -v
python -m pytest core_orchestrator/tests/test_main.py -v
```

All tests use mock LLMs and require no API keys or network access.

## Project Structure

```
enterprise-harness/
├── main.py                              # CLI entry point
├── models_config.yaml                   # Model & route definitions (edit this!)
├── .env.example                         # API key + URL template (with comments)
├── AGENTS.md                            # Orchestrator rules (read-only)
├── README.md                            # This file
├── core_orchestrator/
│   ├── __init__.py                      # Public API exports
│   ├── llm_connector.py                 # LLMConnector Protocol + providers
│   ├── pii_sanitizer.py                 # PII regex sanitizer middleware
│   ├── llm_gateway.py                   # LLM gateway + token overflow
│   ├── model_router.py                  # YAML config + route matching
│   ├── workspace_manager.py             # File-based shared workspace
│   ├── ceo_agent.py                     # CEO orchestrator (state machine)
│   ├── architect_agent.py               # Architect (file-block code producer)
│   ├── evaluator.py                     # Sandbox verifier (syntax + execution)
│   ├── knowledge_manager.py             # Global knowledge base (compound learning)
│   ├── qa_agent.py                      # QA evaluator (binary verdict)
│   ├── resilience_manager.py            # 3-layer escalation + evaluator + knowledge
│   ├── ce_orchestrator.py               # Post-mortem analysis (5 sub-agents)
│   └── tests/                           # 327 tests, all mock-based
│       ├── test_llm_connector.py        # 16 tests
│       ├── test_model_router.py         # 30 tests
│       ├── test_pii_sanitizer.py        # 30 tests
│       ├── test_llm_gateway.py          # 30 tests
│       ├── test_workspace_manager.py    # 30 tests
│       ├── test_ceo_agent.py            # 21 tests
│       ├── test_architect_agent.py      # 15 tests
│       ├── test_qa_agent.py             # 17 tests
│       ├── test_resilience_manager.py   # 15 tests
│       ├── test_ce_orchestrator.py      # 18 tests
│       ├── test_translation_gateway.py  # 16 tests
│       └── test_main.py                 #  7 tests
├── knowledge_base/                      # Design decision docs
└── workspaces/                          # Runtime workspace (gitignored)
```
