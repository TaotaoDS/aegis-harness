"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { ChatInput } from "./components/ChatInput";
import { MessageBubble, ChatMessage, MessageRole } from "./components/MessageBubble";
import { useT } from "@/lib/i18n";

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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ChatPage() {
  const t = useT();

  const [messages, setMessages] = useState<ChatMessage[]>([
    newMsg("bot", t.chat.greeting),
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

  // ── eventToSystemMsg — defined inside component to close over t ───────

  function eventToSystemMsg(type: string, data: Record<string, unknown>): string | null {
    const map: Record<string, string> = {
      "pipeline.phase_change":       t.chat.phaseChange(String(data.phase ?? "")),
      "pipeline.execution_start":    t.chat.executionStart((data.task_count as number) ?? 0),
      "pipeline.execution_complete": t.chat.executionComplete(
        (data.passed as number) ?? 0,
        (data.escalated as number) ?? 0,
      ),
      "ceo.interview_complete":      t.chat.interviewComplete,
      "ceo.plan_complete":           t.chat.planComplete,
      "pipeline.complete":           t.chat.pipelineComplete,
      "pipeline.failed":             t.chat.pipelineFailed,
      "pipeline.rejected":           t.chat.pipelineRejected,
      "evaluator.pass":              t.chat.evaluatorPass((data.file_count as number) ?? 0),
      "qa.pass":                     t.chat.qaPass((data.attempt as number) ?? 1),
    };
    return map[type] ?? null;
  }

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
          addMsg(newMsg("system", t.chat.fileGenerated(String(data.filepath ?? ""))));
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addMsg, t]);

  // ── Send handler (initial requirement) ────────────────────────────────

  const handleSend = useCallback(async (text: string) => {
    if (phase !== "idle" && phase !== "done") return;

    addMsg(newMsg("user", text));
    setPhase("creating");
    addMsg(newMsg("system", t.chat.creating));

    try {
      const id = await createJob(text);
      setJobId(id);
      addMsg(newMsg("system", t.chat.created(id)));
      setPhase("streaming");
      startStreaming(id);
    } catch (err) {
      addMsg(newMsg("system", t.chat.createFailed(String(err))));
      setPhase("error");
    }
  }, [phase, addMsg, startStreaming, t]);

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
      newMsg("bot", t.chat.restart),
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
          <h1 className="text-xl font-bold text-white">{t.chat.title}</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            {t.chat.subtitle}
          </p>
        </div>
        {(phase === "done" || phase === "error") && (
          <button
            onClick={handleRestart}
            className="text-sm px-4 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600
                       text-slate-200 transition-colors"
          >
            {t.chat.newChat}
          </button>
        )}
        {jobId && (
          <a
            href={`/jobs/${jobId}`}
            className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            {t.chat.viewDetails}
          </a>
        )}
      </div>

      {/* Status indicator */}
      {phase === "streaming" && (
        <div className="flex items-center gap-2 text-xs text-violet-300 mb-3 shrink-0">
          <span className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
          {t.chat.agentRunning}
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
            {t.chat.doneMsg}{" "}
            <a href={`/jobs/${jobId}`} className="text-blue-400 hover:underline">
              {t.chat.doneLink}
            </a>
          </div>
        ) : (
          <ChatInput
            onSend={handleSend}
            disabled={isInputDisabled}
            placeholder={
              phase === "idle"
                ? t.chat.placeholder
                : t.chat.waitingPlaceholder
            }
          />
        )}
      </div>
    </div>
  );
}
