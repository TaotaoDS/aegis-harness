"use client";

/**
 * Slide-in drawer listing the user's past chat sessions.
 *
 * Fetches GET /knowledge/sessions on open; clicking a session calls
 * onLoadSession with the full message history so WorkspaceChat can
 * restore the conversation.
 */

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n";

interface SessionSummary {
  id:            string;
  title:         string;
  message_count: number;
  updated_at:    string;
  context_node_ids: string[];
}

interface SessionDetail extends SessionSummary {
  messages: Array<{ id: number; role: string; content: string; created_at: string }>;
}

interface Props {
  open:            boolean;
  onClose:         () => void;
  currentSessionId?: string;
  onLoadSession:   (detail: SessionDetail) => void;
  onNewSession:    () => void;
}

export function HistoryDrawer({ open, onClose, currentSessionId, onLoadSession, onNewSession }: Props) {
  const t = useT();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");
  const [loadingId, setLoadingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError("");
    setLoading(true);
    fetch("/api/proxy/knowledge/sessions?limit=50")
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((data: SessionSummary[]) => setSessions(data))
      .catch(() => setError(t.historyDrawer.loadFailed))
      .finally(() => setLoading(false));
  }, [open, t]);

  const handleLoad = async (sess: SessionSummary) => {
    if (loadingId) return;
    setLoadingId(sess.id);
    try {
      const res = await fetch(`/api/proxy/knowledge/sessions/${sess.id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const detail: SessionDetail = await res.json();
      onLoadSession(detail);
      onClose();
    } catch {
      setError(t.historyDrawer.loadFailed);
    } finally {
      setLoadingId(null);
    }
  };

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px]"
        onClick={onClose}
      />

      {/* Drawer panel */}
      <div className="fixed top-0 right-0 bottom-0 z-50 w-80 max-w-[90vw]
                      bg-slate-900 border-l border-slate-700 shadow-2xl
                      flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 shrink-0">
          <h3 className="text-sm font-semibold text-white">{t.historyDrawer.title}</h3>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { onNewSession(); onClose(); }}
              className="text-[10px] px-2 py-1 rounded border border-violet-600/60
                         text-violet-400 hover:bg-violet-800/40 transition-colors"
            >
              {t.historyDrawer.newSession}
            </button>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white transition-colors w-5 h-5 flex items-center justify-center"
            >
              ✕
            </button>
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto py-2">
          {loading && (
            <p className="text-center text-slate-500 text-xs py-8">{t.historyDrawer.loading}</p>
          )}
          {error && !loading && (
            <p className="text-center text-red-400 text-xs py-8">{error}</p>
          )}
          {!loading && !error && sessions.length === 0 && (
            <p className="text-center text-slate-500 text-xs py-8">{t.historyDrawer.empty}</p>
          )}
          {sessions.map((sess) => {
            const isActive   = sess.id === currentSessionId;
            const isLoading  = loadingId === sess.id;
            const date = sess.updated_at
              ? new Date(sess.updated_at).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
              : "";
            return (
              <button
                key={sess.id}
                onClick={() => handleLoad(sess)}
                disabled={!!loadingId}
                className={`w-full text-left px-4 py-3 border-b border-slate-800 transition-colors
                            hover:bg-slate-800/60 disabled:opacity-60
                            ${isActive ? "bg-violet-900/30 border-l-2 border-l-violet-500" : ""}`}
              >
                <p className="text-xs font-medium text-slate-200 line-clamp-2 leading-snug">
                  {isLoading ? "⌛ " : ""}{sess.title || "(Untitled)"}
                </p>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-[10px] text-slate-500">
                    {t.historyDrawer.msgCount(sess.message_count)}
                  </span>
                  <span className="text-[10px] text-slate-600">{date}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}
