"use client";

/**
 * WorkspaceChat — unified interaction panel for 智控空间 (AI Workspace).
 *
 * Two modes in one input:
 *  - Plain text        → knowledge Q&A grounded in the selected graph context
 *  - /task [type] ...  → creates an Agent job and renders a live TaskCard inline
 *
 * Slash command syntax:
 *   /task <requirement>           — build job (default)
 *   /task build <requirement>     — build job (explicit)
 *   /task update <requirement>    — update job
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { GraphNode } from "./KnowledgeGraph";
import { TaskCard, type JobType } from "./TaskCard";
import { useT } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Role = "user" | "assistant" | "system" | "task";

interface BaseMsg {
  id:      string;
  role:    Role;
  content: string;
}

interface TaskMsg extends BaseMsg {
  role:    "task";
  jobId:   string;
  jobType: JobType;
}

type Message = BaseMsg | TaskMsg;

interface HistoryTurn { role: "user" | "assistant"; content: string }

// ---------------------------------------------------------------------------
// Counters
// ---------------------------------------------------------------------------

let _seq = 0;
const mkMsg = (role: Role, content: string): BaseMsg => ({ id: String(++_seq), role, content });
const mkTask = (jobId: string, jobType: JobType, content: string): TaskMsg => ({
  id: String(++_seq), role: "task", jobId, jobType, content,
});

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  selectedNode:   GraphNode | null;
  contextNodeIds: string[];
  contextTitles:  string[];
  onAutoContext:  (ids: string[], titles: string[]) => void;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function callChat(
  message:        string,
  contextNodeIds: string[],
  history:        HistoryTurn[],
): Promise<string> {
  const res = await fetch("/api/proxy/knowledge/chat", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ message, context_node_ids: contextNodeIds, history }),
  });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error((j as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  const data = await res.json() as { reply: string };
  return data.reply;
}

interface SearchHit { node_id: string; title: string; node_type: string; snippet: string }

async function searchNodes(query: string, limit = 5): Promise<SearchHit[]> {
  const res = await fetch("/api/proxy/knowledge/search", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ query, limit }),
  });
  if (!res.ok) return [];
  const data = await res.json() as { hits?: SearchHit[] };
  return data.hits ?? [];
}

async function createJob(requirement: string, type: JobType): Promise<string> {
  const res = await fetch("/api/proxy/jobs", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ requirement, type, workspace_id: "default" }),
  });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error((j as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  const data = await res.json() as { id: string };
  return data.id;
}

// ---------------------------------------------------------------------------
// Slash-command parser
// ---------------------------------------------------------------------------

interface ParsedInput {
  mode:        "chat" | "task";
  jobType?:    JobType;
  requirement: string;
}

function parseInput(raw: string): ParsedInput {
  const text = raw.trim();

  if (!text.startsWith("/task")) {
    return { mode: "chat", requirement: text };
  }

  // /task [build|update] <requirement>
  const rest = text.slice(5).trimStart();                    // after "/task"
  if (rest.startsWith("update ") || rest === "update") {
    return { mode: "task", jobType: "update", requirement: rest.slice(7).trim() || rest };
  }
  if (rest.startsWith("build ") || rest === "build") {
    return { mode: "task", jobType: "build", requirement: rest.slice(6).trim() || rest };
  }
  return { mode: "task", jobType: "build", requirement: rest };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function WorkspaceChat({
  selectedNode,
  contextNodeIds,
  contextTitles,
  onAutoContext,
}: Props) {
  const t = useT();
  const [messages, setMessages] = useState<Message[]>([
    mkMsg("assistant", t.workspace.greeting),
  ]);
  const [input,   setInput]   = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef             = useRef<HTMLDivElement>(null);
  const textareaRef           = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // System notice when a node is manually selected in the graph
  useEffect(() => {
    if (!selectedNode) return;
    const neighbours = Math.max(0, contextNodeIds.length - 1);
    setMessages((prev) => [
      ...prev,
      mkMsg("system", t.workspace.nodeContextSwitched(selectedNode.title, neighbours)),
    ]);
  // We only want to fire when the selected node itself changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode?.id]);

  // Build conversation history for multi-turn knowledge chat
  const buildHistory = useCallback((): HistoryTurn[] => {
    return messages
      .filter((m): m is BaseMsg => m.role === "user" || m.role === "assistant")
      .slice(-12)
      .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
  }, [messages]);

  // ── Main send handler ────────────────────────────────────────────────────

  const handleSend = useCallback(async () => {
    const raw = input.trim();
    if (!raw || loading) return;

    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const parsed = parseInput(raw);

    // Always show the user's raw message
    setMessages((prev) => [...prev, mkMsg("user", raw)]);

    // ── /task mode ──────────────────────────────────────────────────────────
    if (parsed.mode === "task") {
      if (!parsed.requirement) {
        setMessages((prev) => [
          ...prev,
          mkMsg("system", t.workspace.taskNeedsRequirement),
        ]);
        return;
      }

      setLoading(true);
      setMessages((prev) => [
        ...prev,
        mkMsg("system", t.workspace.taskCreating(parsed.jobType!)),
      ]);

      try {
        const jobId = await createJob(parsed.requirement, parsed.jobType!);
        setMessages((prev) => [
          ...prev,
          mkTask(jobId, parsed.jobType!, parsed.requirement),
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          mkMsg("system", t.workspace.taskCreateFailed(String(err))),
        ]);
      } finally {
        setLoading(false);
      }
      return;
    }

    // ── Knowledge Q&A mode ────────────────────────────────────────────────
    setLoading(true);

    let activeIds    = contextNodeIds;
    let activeTitles = contextTitles;

    // Auto-search when no node is manually selected
    if (activeIds.length === 0) {
      try {
        const hits = await searchNodes(raw, 5);
        if (hits.length > 0) {
          activeIds    = hits.map((h) => h.node_id);
          activeTitles = hits.map((h) => h.title);
          onAutoContext(activeIds, activeTitles);
          const titlesPreview = activeTitles.slice(0, 3).join("、") + (hits.length > 3 ? "…" : "");
          setMessages((prev) => [
            ...prev,
            mkMsg("system", t.workspace.autoMatched(hits.length, titlesPreview)),
          ]);
        }
      } catch {
        // search failure is non-fatal
      }
    }

    try {
      const reply = await callChat(raw, activeIds, buildHistory());
      setMessages((prev) => [...prev, mkMsg("assistant", reply)]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        mkMsg("system", t.workspace.chatRequestFailed(String(err))),
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, contextNodeIds, contextTitles, buildHistory, onAutoContext]);

  // ── Input event handlers ─────────────────────────────────────────────────

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function onInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }

  const hasContext   = contextNodeIds.length > 0;
  const isTaskMode   = input.trimStart().startsWith("/task");
  const canSend      = !loading && input.trim().length > 0;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full">

      {/* ── Header ── */}
      <div className="px-4 py-3 border-b border-stone-200 dark:border-slate-800 shrink-0
                      bg-white dark:bg-[#0a0f1e]">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              {t.workspace.rightHeader}
              {isTaskMode && (
                <span className="text-[10px] px-1.5 py-0.5 rounded font-medium
                                 bg-violet-100 text-violet-700 border border-violet-300
                                 dark:bg-violet-800/60 dark:border-violet-600/40 dark:text-violet-300">
                  {t.workspace.taskBadge}
                </span>
              )}
            </h2>
            <p className="text-[10px] text-slate-500 mt-0.5">
              {hasContext
                ? `✨ ${t.workspace.contextHint} · ${t.workspace.taskModeHint}`
                : `${t.workspace.chatModeIdle.replace(/^💬\s*/, "")} · ${t.workspace.taskModeHint}`}
            </p>
          </div>

          {/* Context badges */}
          {contextTitles.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap justify-end max-w-[52%]">
              {contextTitles.slice(0, 4).map((t, i) => (
                <span
                  key={i}
                  className="text-[9px] px-1.5 py-0.5 rounded-full
                             bg-violet-100 text-violet-700 border border-violet-300
                             dark:bg-violet-900/40 dark:border-violet-700/50 dark:text-violet-300
                             truncate max-w-[80px]"
                  title={t}
                >
                  {t}
                </span>
              ))}
              {contextTitles.length > 4 && (
                <span className="text-[9px] text-slate-500">+{contextTitles.length - 4}</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Hint banner when context is injected ── */}
      {hasContext && (
        <div className="shrink-0 px-4 py-1.5 bg-gradient-to-r from-violet-50 to-transparent
                        dark:from-violet-900/20 dark:to-transparent
                        border-b border-violet-200/50 dark:border-violet-800/30">
          <div className="flex items-center gap-1.5 text-[10px] text-violet-700 dark:text-violet-300">
            <span>⚡</span>
            <span className="font-medium">{t.workspace.contextHint}</span>
            <span className="text-violet-600/70 dark:text-violet-400/70">
              {t.workspace.contextNodesCount(contextTitles.length)}
            </span>
          </div>
        </div>
      )}

      {/* ── Message list ── */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-stone-50 dark:bg-[#0a0f1e]">
        {messages.map((msg) => {

          // System pill
          if (msg.role === "system") {
            return (
              <div key={msg.id} className="flex justify-center">
                <span className="text-[10px] text-slate-600 dark:text-slate-500
                                  bg-stone-200/70 dark:bg-slate-800/60
                                  px-3 py-1 rounded-full text-center max-w-[90%]">
                  {msg.content}
                </span>
              </div>
            );
          }

          // Inline task card (generative UI)
          if (msg.role === "task") {
            const tm = msg as TaskMsg;
            return (
              <div key={msg.id} className="flex justify-start">
                <div className="w-full max-w-[92%]">
                  <TaskCard
                    jobId={tm.jobId}
                    requirement={tm.content}
                    jobType={tm.jobType}
                  />
                </div>
              </div>
            );
          }

          // User / assistant bubbles
          const isUser = msg.role === "user";
          return (
            <div key={msg.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
              <div className={`flex items-end gap-2 max-w-[84%] ${isUser ? "flex-row-reverse" : ""}`}>
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs shrink-0 ${
                  isUser
                    ? "bg-blue-600 text-white"
                    : "bg-violet-600 text-white dark:bg-violet-700"
                }`}>
                  {isUser ? "👤" : "🤖"}
                </div>
                <div className={`px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap shadow-sm ${
                  isUser
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : "bg-white text-slate-800 border border-stone-200 rounded-bl-sm dark:bg-slate-700/80 dark:text-slate-100 dark:border-transparent"
                }`}>
                  {msg.content}
                </div>
              </div>
            </div>
          );
        })}

        {/* Typing indicator */}
        {loading && (
          <div className="flex justify-start">
            <div className="flex items-end gap-2">
              <div className="w-7 h-7 rounded-full bg-violet-600 dark:bg-violet-700 flex items-center justify-center text-xs text-white">🤖</div>
              <div className="px-3.5 py-3 rounded-2xl rounded-bl-sm
                              bg-white border border-stone-200 dark:bg-slate-700/80 dark:border-transparent">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Floating input bar ── */}
      <div className="px-4 pb-4 pt-2 shrink-0 border-t border-stone-200 dark:border-slate-800
                      bg-stone-50 dark:bg-[#0a0f1e]">
        <div className={`flex items-end gap-2 border rounded-xl px-3 py-2 transition-colors shadow-sm
          ${isTaskMode
            ? "bg-violet-50 border-violet-300 focus-within:border-violet-500 dark:bg-violet-950/30 dark:border-violet-600/40 dark:focus-within:border-violet-400/60"
            : "bg-white border-stone-300 focus-within:border-violet-400 dark:bg-slate-800/60 dark:border-slate-600 dark:focus-within:border-violet-500/60"
          }`}
        >
          {/* Attachment icon (decorative — clicking opens upload panel via the left side) */}
          <button
            type="button"
            tabIndex={-1}
            title="附件请使用左侧上传区"
            className="shrink-0 w-7 h-7 mb-0.5 flex items-center justify-center rounded-md
                       text-slate-400 hover:text-slate-700 dark:hover:text-slate-300
                       hover:bg-stone-100 dark:hover:bg-slate-700/40 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>

          <textarea
            ref={textareaRef}
            value={input}
            onChange={onInputChange}
            onKeyDown={onKeyDown}
            disabled={loading}
            rows={1}
            placeholder={t.workspace.inputPlaceholder}
            className="flex-1 bg-transparent text-sm text-slate-800 dark:text-slate-200
                       placeholder-slate-400 dark:placeholder-slate-500
                       resize-none outline-none min-h-[28px] max-h-[160px] leading-relaxed
                       disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!canSend}
            className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-colors
                       bg-violet-600 hover:bg-violet-500 text-white
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isTaskMode ? (
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clipRule="evenodd" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            )}
          </button>
        </div>

        <div className="mt-1.5 flex items-center justify-between">
          <p className="text-[10px] text-slate-500 dark:text-slate-600">
            {isTaskMode
              ? t.workspace.taskModeHint
              : hasContext
                ? t.workspace.askingAbout(contextTitles[0] ?? "")
                : t.workspace.chatModeIdle}
          </p>
          <p className="text-[10px] text-slate-500 dark:text-slate-600">{t.workspace.enterShortcut}</p>
        </div>
      </div>
    </div>
  );
}
