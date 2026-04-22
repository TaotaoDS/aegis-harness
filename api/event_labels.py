"""Maps internal event types to human-readable Chinese labels.

Used by both backend (SSE payload enrichment) and frontend fallback.
"""

from typing import Any, Dict


EVENT_LABELS: Dict[str, str] = {
    # Pipeline lifecycle
    "pipeline.start":             "🚀 任务已启动",
    "pipeline.complete":          "🎉 全部任务完成",
    "pipeline.update_start":      "⚡ 正在分析现有代码库，准备增量更新…",
    "pipeline.update_complete":   "✅ 项目更新完成",
    "pipeline.execution_complete":"📊 执行阶段完成",
    "pipeline.error":             "❌ 流程出错：{error}",
    "pipeline.rejected":          "⛔ 任务已被用户取消",

    # CEO
    "ceo.interviewing":           "💬 正在梳理需求…",
    "ceo.question":               "❓ CEO 提问：{question}",
    "ceo.planning":               "📋 正在制定开发计划…",
    "ceo.plan_created":           "📋 开发计划已就绪，共 {task_count} 个任务",
    "ceo.delegating":             "📤 正在分配任务给开发团队…",
    "ceo.delegated":              "✅ 任务分配完毕，共 {task_count} 个",

    # Architect
    "architect.solving":          "🔨 正在编写代码：{task_id}",
    "architect.llm_response":     "💭 收到 AI 响应，共 {file_count} 个文件",
    "architect.file_written":     "📄 已写入：{filepath}",
    "architect.files_written":    "📦 本轮写入完成",
    "architect.file_read":        "👁 正在查阅：{filepath}",
    "architect.file_write_blocked": "🚫 写入被拦截（等待审批）：{filepath}",
    "architect.zero_files":       "⚠️ 本次未生成任何文件，正在重试…",
    "architect.solve_complete":   "✅ {task_id} 编码完成（第 {attempt} 次）",

    # Evaluator
    "evaluator.running":          "🔬 正在进行沙箱验证…",
    "evaluator.pass":             "✅ 沙箱验证通过",
    "evaluator.fail":             "🔴 沙箱验证失败，反馈给 Architect…",

    # QA
    "qa.reviewing":               "🔍 QA 正在审查代码质量…",
    "qa.pass":                    "✅ 代码审查通过",
    "qa.fail":                    "❌ 代码审查不通过，进入修复流程…",

    # Resilience
    "resilience.attempt_start":   "🔄 开始第 {attempt} 次尝试…",
    "resilience.gateway_selected":"⚙️ 模型已选定",
    "resilience.budget_exceeded": "💸 Token 预算耗尽，停止重试",
    "resilience.escalated":       "🆘 已达最大重试次数，移交人工处理",

    # Knowledge
    "knowledge.lesson_added":     "📚 已记录新经验教训",

    # HITL
    "hitl.approval_required":     "🔴 需要您的批准才能继续",
    "hitl.approved":              "✅ 已批准，继续执行…",
    "hitl.rejected":              "⛔ 已拒绝，操作已取消",

    # CE Orchestrator
    "ce.analyzing":               "📊 正在进行复盘分析…",
    "ce.complete":                "📊 复盘报告已生成",
}


def translate(event_type: str, data: Dict[str, Any]) -> str:
    """Return a human-readable label. Falls back to raw event type."""
    template = EVENT_LABELS.get(event_type, event_type)
    try:
        return template.format(**data)
    except (KeyError, ValueError):
        return template
