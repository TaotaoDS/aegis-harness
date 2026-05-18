"""Maps internal event types to human-readable English labels.

Used by both backend (SSE payload enrichment) and frontend fallback.
"""

from typing import Any, Dict


EVENT_LABELS: Dict[str, str] = {
    # Pipeline lifecycle
    "pipeline.start":             "🚀 Task started",
    "pipeline.complete":          "🎉 All tasks completed",
    "pipeline.update_start":      "⚡ Analysing existing codebase, preparing incremental update…",
    "pipeline.update_complete":   "✅ Project update complete",
    "pipeline.execution_complete":"📊 Execution phase complete",
    "pipeline.error":             "❌ Pipeline error: {error}",
    "pipeline.rejected":          "⛔ Task cancelled by user",

    # CEO
    "ceo.interviewing":           "💬 Clarifying requirements…",
    "ceo.question":               "❓ CEO question: {question}",
    "ceo.planning":               "📋 Drafting development plan…",
    "ceo.plan_created":           "📋 Development plan ready — {task_count} task(s)",
    "ceo.delegating":             "📤 Delegating tasks to the development team…",
    "ceo.delegated":              "✅ Delegation complete — {task_count} task(s) assigned",

    # Architect
    "architect.solving":          "🔨 Writing code: {task_id}",
    "architect.llm_response":     "💭 AI response received — {file_count} file(s)",
    "architect.file_written":     "📄 Written: {filepath}",
    "architect.files_written":    "📦 Round write complete",
    "architect.file_read":        "👁 Reading: {filepath}",
    "architect.file_write_blocked": "🚫 Write blocked (awaiting approval): {filepath}",
    "architect.zero_files":       "⚠️ No files generated this round, retrying…",
    "architect.solve_complete":   "✅ {task_id} coding complete (attempt {attempt})",

    # Evaluator
    "evaluator.running":          "🔬 Running sandbox validation…",
    "evaluator.pass":             "✅ Sandbox validation passed",
    "evaluator.fail":             "🔴 Sandbox validation failed — feeding back to Architect…",

    # QA
    "qa.reviewing":               "🔍 QA reviewing code quality…",
    "qa.pass":                    "✅ Code review passed",
    "qa.fail":                    "❌ Code review failed — entering fix cycle…",

    # Resilience
    "resilience.attempt_start":   "🔄 Starting attempt {attempt}…",
    "resilience.gateway_selected":"⚙️ Model selected",
    "resilience.budget_exceeded": "💸 Token budget exhausted — stopping retries",
    "resilience.escalated":       "🆘 Max retries reached — escalating to human review",

    # Knowledge
    "knowledge.lesson_added":     "📚 New lesson recorded",

    # HITL
    "hitl.approval_required":     "🔴 Your approval is required to continue",
    "hitl.approved":              "✅ Approved — continuing execution…",
    "hitl.rejected":              "⛔ Rejected — operation cancelled",

    # CEO interview confidence
    "ceo.interview_complete":     "✅ Requirements interview complete — confidence {confidence}%",

    # Reflection Agent (Compound Learning)
    "reflection.start":           "🔍 Running post-mortem analysis…",
    "reflection.solution_saved":  "💡 Lesson learned: {problem}",
    "reflection.complete":        "📚 Post-mortem complete — {saved} lesson(s) saved",

    # Experience Distiller (Compound Engineering)
    "distiller.start":                "🧪 Running compound experience distillation…",
    "distiller.enrichment_complete":  "🔬 Enrichment: {symptoms} symptoms, {failed_attempts} failures, {root_causes} root causes",
    "distiller.indexed":              "📇 Indexed: {problem}",
    "distiller.complete":             "🧬 Distillation complete — {saved} saved, {indexed} indexed",

    # CE Orchestrator
    "ce.analyzing":               "📊 Running retrospective analysis…",
    "ce.complete":                "📊 Retrospective report generated",
}


def translate(event_type: str, data: Dict[str, Any]) -> str:
    """Return a human-readable label. Falls back to raw event type."""
    template = EVENT_LABELS.get(event_type, event_type)
    try:
        return template.format(**data)
    except (KeyError, ValueError):
        return template
