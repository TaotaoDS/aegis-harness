"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { ChatInput } from "./components/ChatInput";
import { MessageBubble, ChatMessage, MessageRole } from "./components/MessageBubble";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Phase =
  | "idle"          // waiting for first input
  | "creating"      // POST /jobs in flight
  | "streaming"     // SSE connected, pipeline running
  | "done"          // pipeline complete
  | "error";        // unrecoverable error

let _msgSeq = 0;
function newMsg(role: MessageRole, content: string, options?: string[]): ChatMessage {
  return { id: String(++_msgSeq), role, content, options };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function createJob(requirement: string): Promise<string> {
  const res = await fetch("/api/proxy/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requirement, type: "build" }),
  });
  if (!res.ok) throw new Error(`Failed to create job: ${res.status}`);
  const data = await res.json();
  return data.id as string;
}

/** Map SSE event type → human-readable chat system message */
function eventToSystemMsg(type: string, data: Record<string, unknown>): string | null {
  const map: Record<string, string> = {
    "pipeline.phase_change":      `阶段变更 → ${data.phase ?? ""}`,
    "pipeline.execution_start":   `开始执行 ${data.task_count ?? ""} 个任务…`,
    "pipeline.execution_complete":`执行完成 ✓  通过 ${data.passed ?? 0}  升级 ${data.escalated ?? 0}`,
    "ceo.interview_complete":     "需求收集完成，正在生成计划…",
    "ceo.plan_complete":          "任务分解完成",
    "pipeline.complete":          "✅ 任务完成！",
    "pipeline.failed":            "❌ 任务失败",
    "pipeline.rejected":          "⚠️ 任务被拒绝",
    "evaluator.pass":             `评估通过 (${data.file_count ?? 0} 个文件)`,
    "qa.pass":                    `QA 审核通过 (第 ${data.attempt ?? 1} 次)`,
  };
  return map[type] ?? null;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    newMsg("bot",
      "你好！我是 AegisHarness AI 助手。\n请告诉我您想要构建什么，我会帮您分析需求、制定计划并自动执行开发任务。"),
  ]);
  const [phase, setPhase]   = useState<Phase>("idle");
  const [jobId, setJobId]   = useState<string | null>(null);
  const bottomRef           = useRef<HTMLDivElement>(null);
  const esRef               = useRef<EventSource | null>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Cleanup SSE on unmount
  useEffect(() => () => esRef.current?.close(), []);

  const addMsg = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  // ── Start SSE listener ─────────────────────────────────────────────────

  const startStreaming = useCallback((id: string) => {
    esRef.current?.close();
    const es = new EventSource(`/api/proxy/jobs/${id}/events`);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        const { type, label, data = {} } = payload;

        // CEO asks an interview question
        if (type === "ceo.interview_question" || type === "ceo.question") {
          const question = (data.question as string) ?? label ?? "";
          const options  = (data.options as string[]) ?? [];
          if (question) {
            addMsg(newMsg("bot", question, options.length ? options : undefined));
          }
          return;
        }

        // Architect writes a file
        if (type === "architect.file_written") {
          addMsg(newMsg("system", `📄 生成文件: ${data.filepath ?? ""}`));
          return;
        }

        // Pipeline terminal events
        if (type === "pipeline.complete" || type === "pipeline.failed" || type === "pipeline.rejected") {
          const msg = eventToSystemMsg(type, data as Record<string, unknown>);
          if (msg) addMsg(newMsg("system", msg));
          setPhase("done");
          es.close();
          return;
        }

        // Generic system events
        const sysMsg = eventToSystemMsg(type, data as Record<string, unknown>);
        if (sysMsg) addMsg(newMsg("system", sysMsg));

      } catch {
        // Ignore malformed events
      }
    };

    es.onerror = () => {
      // SSE disconnects after pipeline completes — only treat as error if still running
      setPhase((prev) => {
        if (prev === "streaming") {
          es.close();
          return "error";
        }
        return prev;
      });
    };
  }, [addMsg]);

  // ── Send handler (initial requirement) ────────────────────────────────

  const handleSend = useCallback(async (text: string) => {
    if (phase !== "idle" && phase !== "done") return;

    addMsg(newMsg("user", text));
    setPhase("creating");
    addMsg(newMsg("system", "正在创建任务…"));

    try {
      const id = await createJob(text);
      setJobId(id);
      addMsg(newMsg("system", `任务已创建 (ID: ${id})，开始执行…`));
      setPhase("streaming");
      startStreaming(id);
    } catch (err) {
      addMsg(newMsg("system", `创建任务失败: ${String(err)}`));
      setPhase("error");
    }
  }, [phase, addMsg, startStreaming]);

  // ── Options click → treat as a follow-up message ──────────────────────

  const handleOption = useCallback((option: string) => {
    if (phase === "idle") {
      handleSend(option);
    }
  }, [phase, handleSend]);

  // ── Restart ────────────────────────────────────────────────────────────

  const handleRestart = () => {
    esRef.current?.close();
    setMessages([
      newMsg("bot", "好的，让我们重新开始。请告诉我您想要构建什么？"),
    ]);
    setPhase("idle");
    setJobId(null);
  };

  // ── Render ─────────────────────────────────────────────────────────────

  const isInputDisabled = phase === "creating" || phase === "streaming";

  return (
    <div className="flex flex-col h-[calc(100vh-80px)] max-w-3xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div>
          <h1 className="text-xl font-bold text-white">AI 对话助手</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            描述您的需求，AI 将自动规划并执行开发任务
          </p>
        </div>
        {(phase === "done" || phase === "error") && (
          <button
            onClick={handleRestart}
            className="text-sm px-4 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600
                       text-slate-200 transition-colors"
          >
            新对话
          </button>
        )}
        {jobId && (
          <a
            href={`/jobs/${jobId}`}
            className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            查看详情 →
          </a>
        )}
      </div>

      {/* Status indicator */}
      {phase === "streaming" && (
        <div className="flex items-center gap-2 text-xs text-violet-300 mb-3 shrink-0">
          <span className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
          Agent 正在执行中…
        </div>
      )}

      {/* Message list */}
      <div className="flex-1 overflow-y-auto pr-1 space-y-1">
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onOptionClick={handleOption}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 pt-3">
        {phase === "done" ? (
          <div className="text-center text-sm text-slate-400 py-3">
            任务已完成。点击「新对话」开始新任务，或{" "}
            <a href={`/jobs/${jobId}`} className="text-blue-400 hover:underline">
              查看执行详情
            </a>
            。
          </div>
        ) : (
          <ChatInput
            onSend={handleSend}
            disabled={isInputDisabled}
            placeholder={
              phase === "idle"
                ? "描述您想要构建的内容，例如：开发一个 REST API 服务器…"
                : "Agent 执行中，请稍候…"
            }
          />
        )}
      </div>
    </div>
  );
}
