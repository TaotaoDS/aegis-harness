"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  jobId: string;
  question: string;
  /** Called after the answer is successfully submitted */
  onAnswered: () => void;
}

/**
 * CEO Interview Panel — shown when a `ceo.question` event arrives.
 *
 * Renders the CEO's clarifying question and an answer input field.
 * On submit, POSTs to /api/proxy/jobs/{jobId}/answer and notifies the parent.
 *
 * The panel is deliberately prominent (yellow border, full-width) so users
 * know the pipeline is paused and waiting for their input.
 */
export function InterviewPanel({ jobId, question, onAnswered }: Props) {
  const [answer,     setAnswer]     = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error,      setError]      = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-focus the text area when the panel appears
  useEffect(() => {
    inputRef.current?.focus();
  }, [question]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = answer.trim();
    if (!trimmed) {
      setError("请输入回答后再提交");
      return;
    }

    setSubmitting(true);
    setError("");

    try {
      const res = await fetch(`/api/proxy/jobs/${jobId}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answer: trimmed }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data?.detail ?? `提交失败 (${res.status})`);
        return;
      }

      setAnswer("");
      onAnswered();
    } catch {
      setError("网络错误，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Cmd/Ctrl + Enter submits
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      handleSubmit(e as unknown as React.FormEvent);
    }
  };

  return (
    <div className="border border-yellow-500/60 bg-yellow-900/10 rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-yellow-500/30 bg-yellow-900/20">
        <span className="live-dot w-2 h-2 bg-yellow-400 rounded-full shrink-0" />
        <span className="text-yellow-300 text-sm font-medium">
          CEO 正在访谈 — 请回答以下问题
        </span>
        <span className="ml-auto text-xs text-yellow-500/70">
          回答越详细，生成的计划越精准
        </span>
      </div>

      {/* Question */}
      <div className="px-5 py-4">
        <p className="text-white text-base leading-relaxed font-medium">
          {question}
        </p>
      </div>

      {/* Answer form */}
      <form onSubmit={handleSubmit} className="px-5 pb-5 space-y-3">
        <textarea
          ref={inputRef}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          placeholder="输入你的回答… (Ctrl+Enter 快速提交)"
          disabled={submitting}
          className="w-full bg-slate-800 border border-slate-600 focus:border-yellow-500 rounded-xl px-4 py-3 text-slate-200 text-sm resize-none focus:outline-none transition-colors disabled:opacity-50"
        />

        {error && (
          <p className="text-red-400 text-xs">{error}</p>
        )}

        <div className="flex items-center justify-between">
          <p className="text-slate-500 text-xs">
            CEO 置信度达到 95% 后将自动进入规划阶段
          </p>
          <button
            type="submit"
            disabled={submitting || !answer.trim()}
            className="bg-yellow-600 hover:bg-yellow-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors flex items-center gap-2"
          >
            {submitting ? (
              <>
                <span className="animate-spin">⟳</span> 提交中…
              </>
            ) : (
              <>
                <span>↩</span> 提交回答
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
