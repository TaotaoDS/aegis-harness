/**
 * Frontend mirror of api/event_labels.py.
 *
 * Used as a fallback when the backend label field is missing (e.g. during
 * development against an older API version).
 */

export const EVENT_LABELS: Record<string, string> = {
  // Pipeline lifecycle
  "pipeline.start":              "🚀 Task started",
  "pipeline.complete":           "🎉 All tasks completed",
  "pipeline.update_start":       "⚡ Analysing existing codebase, preparing incremental update…",
  "pipeline.update_complete":    "✅ Project update complete",
  "pipeline.execution_complete": "📊 Execution phase complete",
  "pipeline.error":              "❌ Pipeline error",
  "pipeline.rejected":           "⛔ Task cancelled by user",

  // CEO
  "ceo.interviewing":            "💬 Clarifying requirements…",
  "ceo.question":                "❓ CEO question pending",
  "ceo.planning":                "📋 Drafting development plan…",
  "ceo.plan_created":            "📋 Development plan ready",
  "ceo.delegating":              "📤 Delegating tasks to the development team…",
  "ceo.delegated":               "✅ Delegation complete",

  // Architect
  "architect.solving":           "🔨 Writing code",
  "architect.llm_response":      "💭 AI response received",
  "architect.file_written":      "📄 File written",
  "architect.files_written":     "📦 Round write complete",
  "architect.file_read":         "👁 Reading file",
  "architect.file_write_blocked":"🚫 Write blocked (awaiting approval)",
  "architect.zero_files":        "⚠️ No files generated this round, retrying…",
  "architect.solve_complete":    "✅ Coding complete",

  // Evaluator
  "evaluator.running":           "🔬 Running sandbox validation…",
  "evaluator.pass":              "✅ Sandbox validation passed",
  "evaluator.fail":              "🔴 Sandbox validation failed — feeding back to Architect…",

  // QA
  "qa.reviewing":                "🔍 QA reviewing code quality…",
  "qa.pass":                     "✅ Code review passed",
  "qa.fail":                     "❌ Code review failed — entering fix cycle…",

  // Resilience
  "resilience.attempt_start":    "🔄 Starting new attempt…",
  "resilience.gateway_selected": "⚙️ Model selected",
  "resilience.budget_exceeded":  "💸 Token budget exhausted — stopping retries",
  "resilience.escalated":        "🆘 Max retries reached — escalating to human review",

  // Knowledge
  "knowledge.lesson_added":      "📚 New lesson recorded",

  // HITL
  "hitl.approval_required":      "🔴 Your approval is required to continue",
  "hitl.approved":               "✅ Approved — continuing execution…",
  "hitl.rejected":               "⛔ Rejected — operation cancelled",

  // CEO interview confidence
  "ceo.interview_complete":      "✅ Requirements interview complete",

  // Reflection Agent (Compound Learning)
  "reflection.start":            "🔍 Running post-mortem analysis…",
  "reflection.solution_saved":   "💡 Lesson saved",
  "reflection.complete":         "📚 Post-mortem complete — lessons saved",

  // CE Orchestrator
  "ce.analyzing":                "📊 Running retrospective analysis…",
  "ce.complete":                 "📊 Retrospective report generated",
};

/** Return a human-readable label for an event type, using the backend-provided
 *  label first, then the frontend lookup table, then the raw type as fallback. */
export function getLabel(type: string, backendLabel?: string): string {
  if (backendLabel) return backendLabel;
  return EVENT_LABELS[type] ?? type;
}

/** Events that indicate the pipeline has finished (success or failure). */
export const TERMINAL_EVENTS = new Set([
  "pipeline.complete",
  "pipeline.error",
  "pipeline.rejected",
]);

/** Events that should trigger the HITL approval modal. */
export const HITL_EVENTS = new Set(["hitl.approval_required"]);

/** Events that should trigger the CEO interview input panel. */
export const INTERVIEW_EVENTS = new Set(["ceo.question"]);

/** Events that clear the interview panel (interview done or pipeline moved on). */
export const INTERVIEW_DONE_EVENTS = new Set([
  "ceo.interview_complete",
  "ceo.planning",
]);

/** Events that deserve a rich "generative" card rather than a plain text row. */
export const RICH_EVENTS = new Set([
  "ceo.plan_created",
  "architect.file_written",
  "qa.pass",
  "qa.fail",
  "evaluator.pass",
  "evaluator.fail",
  "pipeline.complete",
  "pipeline.execution_complete",
  "pipeline.update_complete",
]);
