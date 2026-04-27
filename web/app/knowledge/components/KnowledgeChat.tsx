"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { GraphNode } from "./KnowledgeGraph";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Role = "user" | "assistant" | "system";

interface Message {
  id:      string;
  role:    Role;
  content: string;
}

let _seq = 0;
const mkMsg = (role: Role, content: string): Message => ({
  id: String(++_seq),
  role,
  content,
});

interface Props {
  selectedNode:   GraphNode | null;
  contextNodeIds: string[];
  contextTitles:  string[];
  /** Called when the chat auto-selects nodes via keyword search */
  onAutoContext:  (ids: string[], titles: string[]) => void;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

interface HistoryTurn { role: "user" | "assistant"; content: string }

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
    throw new Error(j.detail ?? `HTTP ${res.status}`);
  }
  const data = await res.json();
  return data.reply as string;
}

interface SearchHit { node_id: string; title: string; node_type: string; snippet: string }

async function searchNodes(query: string, limit = 5): Promise<SearchHit[]> {
  const res = await fetch("/api/proxy/knowledge/search", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ query, limit }),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return (data.hits ?? []) as SearchHit[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function KnowledgeChat({ selectedNode, contextNodeIds, contextTitles, onAutoContext }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    mkMsg("assistant", "你好！请在左侧图谱中选择一个节点，我将基于该节点及其关联内容来回答你的问题。也可以直接提问，我会自动匹配相关节点。"),
  ]);
  const [input,   setInput]   = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef             = useRef<HTMLDivElement>(null);
  const textareaRef           = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // System notice when manually selected node changes
  useEffect(() => {
    if (!selectedNode) return;
    setMessages((prev) => [
      ...prev,
      mkMsg("system", `🔗 上下文已切换为「${selectedNode.title}」及其 ${Math.max(0, contextNodeIds.length - 1)} 个关联节点`),
    ]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode?.id]);

  const buildHistory = useCallback((): HistoryTurn[] => {
    return messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .slice(-12)
      .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    if (textareaRef.current) { textareaRef.current.style.height = "auto"; }
    setMessages((prev) => [...prev, mkMsg("user", text)]);
    setLoading(true);

    let activeIds   = contextNodeIds;
    let activeTitles = contextTitles;

    // ── Auto-search when no node is manually selected ─────────────────────
    if (activeIds.length === 0) {
      try {
        const hits = await searchNodes(text, 5);
        if (hits.length > 0) {
          activeIds    = hits.map((h) => h.node_id);
          activeTitles = hits.map((h) => h.title);
          onAutoContext(activeIds, activeTitles);
          setMessages((prev) => [
            ...prev,
            mkMsg("system", `🔍 自动匹配到 ${hits.length} 个相关节点：${activeTitles.slice(0, 3).join("、")}${hits.length > 3 ? "…" : ""}`),
          ]);
        }
      } catch {
        // search failure is non-fatal
      }
    }

    try {
      const reply = await callChat(text, activeIds, buildHistory());
      setMessages((prev) => [...prev, mkMsg("assistant", reply)]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        mkMsg("system", `⚠️ 请求失败：${err}`),
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, contextNodeIds, contextTitles, buildHistory, onAutoContext]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function onInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const el = textareaRef.current;
    if (el) { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 140)}px`; }
  }

  const hasContext = contextNodeIds.length > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700 shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">知识问答</h2>
            <p className="text-[10px] text-slate-500 mt-0.5">
              {hasContext ? "基于选中节点网络的 AI 对话" : "直接提问将自动匹配相关节点"}
            </p>
          </div>
          {contextTitles.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap justify-end max-w-[55%]">
              {contextTitles.slice(0, 4).map((t, i) => (
                <span
                  key={i}
                  className="text-[9px] px-1.5 py-0.5 rounded-full bg-violet-900/40
                             border border-violet-700/50 text-violet-300 truncate max-w-[80px]"
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

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((msg) => {
          if (msg.role === "system") {
            return (
              <div key={msg.id} className="flex justify-center">
                <span className="text-[10px] text-slate-500 bg-slate-800/60
                                  px-3 py-1 rounded-full text-center max-w-[90%]">
                  {msg.content}
                </span>
              </div>
            );
          }

          const isUser = msg.role === "user";
          return (
            <div key={msg.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
              <div className={`flex items-end gap-2 max-w-[82%] ${isUser ? "flex-row-reverse" : ""}`}>
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs shrink-0 ${
                  isUser ? "bg-blue-600" : "bg-violet-700"
                }`}>
                  {isUser ? "👤" : "🤖"}
                </div>
                <div className={`px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                  isUser
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : "bg-slate-700/80 text-slate-100 rounded-bl-sm"
                }`}>
                  {msg.content}
                </div>
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex justify-start">
            <div className="flex items-end gap-2">
              <div className="w-7 h-7 rounded-full bg-violet-700 flex items-center justify-center text-xs">🤖</div>
              <div className="px-3.5 py-3 rounded-2xl rounded-bl-sm bg-slate-700/80">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <span key={i} className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="px-4 pb-4 pt-2 shrink-0 border-t border-slate-800">
        <div className="flex items-end gap-2 bg-slate-800/60 border border-slate-600
                        rounded-xl px-3 py-2 focus-within:border-violet-500/60 transition-colors">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={onInputChange}
            onKeyDown={onKeyDown}
            disabled={loading}
            rows={1}
            placeholder={
              hasContext
                ? `基于「${contextTitles[0] ?? "…"}」提问…`
                : "直接提问，系统将自动匹配相关节点…"
            }
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-500
                       resize-none outline-none min-h-[28px] max-h-[140px] leading-relaxed
                       disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="shrink-0 w-8 h-8 rounded-lg bg-violet-600 hover:bg-violet-500
                       disabled:opacity-40 disabled:cursor-not-allowed flex items-center
                       justify-center transition-colors"
          >
            <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                    d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        </div>
        <p className="mt-1.5 text-[10px] text-slate-600 text-right">
          Enter 发送 · Shift+Enter 换行
        </p>
      </div>
    </div>
  );
}
