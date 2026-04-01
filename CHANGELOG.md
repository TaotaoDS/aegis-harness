# Changelog

All notable changes to this project will be documented in this file.

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
