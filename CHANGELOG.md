# Changelog

All notable changes to this project will be documented in this file.

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
