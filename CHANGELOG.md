# Changelog

All notable changes to this project will be documented in this file.

## [0.6.0] — 2026-04-02

### Breaking Changes

- **Architect agent refactored to native Tool Use (Function Calling)**
  (`architect_agent.py`):
  The fragile regex-based `parse_file_blocks()` text parser has been
  **completely deleted** and replaced with LLM native Tool Use.

  A `write_file(filepath, content)` tool is registered with the LLM via the
  provider's tools API parameter. The system prompt enforces that ALL code
  must be submitted via `write_file` tool calls — inline code blocks are
  explicitly forbidden.

  **ArchitectAgent constructor change:**
  ```python
  # Before (v0.5.x):
  ArchitectAgent(gateway=LLMGateway, workspace=..., ...)
  # After (v0.6.0):
  ArchitectAgent(tool_llm=Callable, workspace=..., ...)
  ```

  `tool_llm` signature: `(system: str, user_prompt: str, tools: List[Dict]) -> List[ToolCall]`

- **ResilienceManager constructor change:**
  Replaced `gateway_factory` / `escalated_gateway_factory` with
  `tool_llm` / `escalated_tool_llm` for the Architect. QA gateway unchanged.

- **`run_execution()` accepts `tool_llm` parameter:**
  New optional `tool_llm` and `escalated_tool_llm` kwargs. For backward
  compatibility with text-based LLMs, `_make_tool_llm_from_text_llm()` shim
  wraps a `Callable[[str], str]` into a tool_llm by parsing `===FILE:===`
  blocks from the text response.

### Major Features

- **`ToolCall` dataclass** (`llm_connector.py`):
  Provider-agnostic representation of a tool invocation with `name` and
  `arguments` fields.

- **`call_with_tools()` on both connectors** (`llm_connector.py`):
  Multi-turn tool loop implementation for OpenAI and Anthropic APIs.
  Handles provider-specific tool schema conversion (OpenAI `functions` format
  vs Anthropic `input_schema` format) and result feeding across rounds.
  Loops until `stop` / `end_turn` or `max_rounds` (default 10).

- **`ModelRouter.call_with_tools()` + `as_tool_llm()`** (`model_router.py`):
  Router-level tool dispatch and factory method for creating tool_llm
  callables bound to a resolved model.

- **`WRITE_FILE_TOOL` schema** (`architect_agent.py`):
  Provider-agnostic tool definition exported for external use and testing.

### Deleted

- `parse_file_blocks()` — all regex-based file extraction (3-tier strategy
  chain, `_FILE_BLOCK_RE`, `_FENCED_BLOCK_RE`, `_LABEL_RE`, etc.)
- All related helper functions (`_looks_like_filepath`, `_clean_path`,
  `_extract_filename_from_comment`, `_strip_filename_comment`,
  `_get_pre_context`, `_strategy_file_blocks`, `_strategy_markdown_blocks`)

### Tests

- 386 tests total: deleted 24 regex parser tests (TestParseFileBlocks,
  TestMarkdownFallback), added 10 Tool Use protocol tests
  (TestToolUseProtocol, TestEventBusIntegration).

## [0.5.0] — 2026-04-02

### Major Features

- **Real-time observability event bus** (`event_bus.py`):
  New `EventBus` module provides publish-subscribe observability for the
  entire Architect → Evaluator → QA pipeline. Two output backends:
  - **Terminal renderer**: ANSI-colored event stream on stderr with
    agent-aware color mapping (cyan=Architect, yellow=Evaluator,
    blue=QA, magenta=Resilience, red=errors, green=success).
  - **Audit file logger**: append-only `_workspace/execution.log` for
    `tail -f` monitoring from a separate terminal.

  22 emit points across 4 agents (ArchitectAgent, Evaluator, QAAgent,
  ResilienceManager) covering: task solving, file writing, sandbox
  verification, QA review, retry escalation, budget checks, and
  pipeline lifecycle.

  Zero blast radius: all agents accept `bus=None` (defaults to `NullBus`),
  existing tests unchanged. `ListBus` test double provided for event
  assertions.

### Infrastructure

- `main.py` wires the bus via `bus_from_workspace()` factory and passes
  it through `run_execution()` → `ResilienceManager` → sub-agents.
- TTY detection gates ANSI codes; non-TTY streams get plain text.

### Tests

- 384 tests total (+42 new): test_event_bus covers color mapping,
  terminal rendering, file logging, NullBus/ListBus, factory, and
  agent integration (Architect/Evaluator/QA emit verification).

## [0.4.0] — 2026-04-02

### Major Features

- **Workspace directory isolation** (`workspace_manager.py`):
  New `isolated=True` mode transparently routes runtime state files (tasks/,
  artifacts/, feedback/, escalations/, plan.md, etc.) to `_workspace/` subdirectory,
  while keeping deliverables in `deliverables/`. Zero changes required to agent code —
  routing is transparent via `_route_path()` / `_unroute_path()`.
  `list_files()` strips the `_workspace/` prefix so agents see the same logical paths.

- **Deliverables path migration** (`architect_agent.py`, `evaluator.py`):
  Architect now writes code files to `deliverables/` instead of `src/`.
  Evaluator validates files under `deliverables/` prefix. Clean physical
  separation between runtime state and final code output.

### Bug Fixes

- **Zero-file guard in ResilienceManager** (`resilience_manager.py`):
  When Architect produces no `===FILE: path===` blocks (empty LLM output),
  the system now immediately writes feedback "Architect produced 0 code files"
  and retries, instead of sending an empty artifact to QA. This prevents the
  wasteful 3× QA rejection cycle seen in snake_game_v4 task_2/task_5 failures.

- **Python 3.9 compatibility** (`model_router.py`):
  Fixed `str | Path` union syntax (PEP 604) that fails on Python 3.9.
  Changed to `Union[str, Path]` from `typing`.

### Tests

- 342 tests total (+15 new): 13 isolated-mode workspace tests, 3 zero-file
  detection tests. All existing tests updated for `src/` → `deliverables/`
  migration and zero-file guard behavior.

## [0.3.0] — 2026-04-02

### Major Features

- **Architect file-block protocol (`===FILE: path===`)**:
  Architect agent now writes physical code files to workspace via structured
  `===FILE: path===` markers parsed from LLM output. New `parse_file_blocks()`
  function, `write_file()`/`read_file()` tools, and knowledge context injection.
  System prompt rewritten to enforce CODE PRODUCER role — specification-only
  responses are explicitly rejected.

- **RLVR Evaluator (`evaluator.py`)**:
  New `Evaluator` class runs sandbox verification between Architect and QA:
  validates file existence, Python syntax (`py_compile`), JS syntax (`node --check`),
  and HTML structure. Failures produce structured error feedback injected back
  to Architect for retry. Integrated into ResilienceManager pipeline.

- **Global Knowledge Base (`knowledge_manager.py`)**:
  New `KnowledgeManager` class implements compound learning:
  `append_lesson()` writes bug/fix/guide entries to `global_knowledge_base.md`;
  `load_knowledge()` injects accumulated lessons into Architect prompts before
  each task. Lessons auto-captured after successful retries (attempt > 1).

- **Configurable execution parameters** (`models_config.yaml`):
  New `execution` block: `max_retries`, `eval_timeout`, `token_budget`,
  `token_threshold` — all read dynamically by ResilienceManager via main.py.

### Bug Fixes

- **task_5 snake_game_v3 manual fix**: Produced 4 physical implementation files
  (index.html, style.css, ui.js, app.js) addressing all 5 QA failures:
  specification→code, historical scores list, devicePixelRatio, accessibility,
  responsive layout.

### Tests

- 327 tests total (+47 new): test_architect_agent (30), test_evaluator (18),
  test_knowledge_manager (9), test_resilience_manager (24 including evaluator/knowledge).

## [0.2.0] — 2026-04-01

### Bug Fixes

- **CE Orchestrator `_format_postmortem` crash** (`AttributeError: 'list' object has no attribute 'get'`):
  Sub-agents (e.g., `plan_prevention`) may return a bare JSON list instead of a dict.
  Added `_safe_dict()` helper that wraps lists and rejects non-dict/non-list values,
  applied to all 5 sub-agent results before formatting. (#ce-179)

### Enhancements

- **Global `max_tokens` raised to 8192**: All models in `models_config.yaml`
  (active and commented-out templates) now default to `max_tokens: 8192`.
  This eliminates premature output truncation for Architect solutions and
  CE Orchestrator post-mortems.

- **Architect incremental output discipline**: System prompt now includes
  `CRITICAL OUTPUT RULES` that:
  1. Forbid dumping all code in a single response.
  2. Require per-module breakdown (file path, purpose, public API, ≤40-line outline).
  3. For implementations >120 lines, output only architecture overview and
     request incremental workspace file writes.
  This prevents token-limit truncation and improves solution quality.

### Infrastructure

- **Git repository initialized** with full project baseline commit.

## [0.1.0] — 2026-03-31

Initial release — 9-phase multi-agent orchestration harness.

- PII Sanitizer, LLM Gateway, Model Router, Workspace Manager
- CEO Agent (reverse interview + plan + delegate + translation gateway)
- Architect Agent, QA Agent, Resilience Manager (3-layer escalation)
- CE Orchestrator (5 sub-agent post-mortem)
- Model-Agnostic LLM Connector (`OpenAIConnector`, `AnthropicConnector`, `register_connector()`)
- Robust JSON parser (`parse_llm_json` — 4-strategy)
- CLI entry point (`main.py`) with checkpoint/resume
- 272 tests, all mock-based
