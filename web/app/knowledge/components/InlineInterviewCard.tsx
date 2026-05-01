"use client";

import { useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n";

interface Props {
  jobId:       string;
  question:    string;
  answered?:   string;
  expired?:    boolean;
  onAnswered:  (answer: string) => void;
}

export function InlineInterviewCard({ jobId, question, answered, expired, onAnswered }: Props) {
  const t = useT();
  const [answer,     setAnswer]     = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error,      setError]      = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!answered && !expired) inputRef.current?.focus();
  }, [answered, expired]);

  const disabled = !!answered || !!expired;

  const handleSubmit = async () => {
    const trimmed = answer.trim();
    if (!trimmed || submitting || disabled) return;

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
        setError((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
        return;
      }
      setAnswer("");
      onAnswered(trimmed);
    } catch {
      setError(t.interview.errorNetwork);
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  const borderColor = answered
    ? "border-green-400/50 dark:border-green-700/40"
    : expired
      ? "border-slate-300 dark:border-slate-700/40"
      : "border-yellow-400/60 dark:border-yellow-600/40";

  const bgColor = answered
    ? "bg-green-50 dark:bg-green-900/10"
    : expired
      ? "bg-slate-50 dark:bg-slate-800/30"
      : "bg-yellow-50 dark:bg-yellow-900/10";

  return (
    <div className={`rounded-xl border ${borderColor} ${bgColor} overflow-hidden text-xs w-full transition-colors`}>
      {/* Header */}
      <div className="px-3 py-2 border-b border-stone-200/50 dark:border-slate-700/30
                      flex items-center gap-2">
        {!disabled && (
          <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse shrink-0" />
        )}
        {answered && (
          <span className="text-green-600 dark:text-green-400 shrink-0">✓</span>
        )}
        {expired && (
          <span className="text-slate-400 shrink-0">—</span>
        )}
        <span className={`font-medium text-xs ${
          answered
            ? "text-green-700 dark:text-green-300"
            : expired
              ? "text-slate-500 dark:text-slate-400"
              : "text-yellow-700 dark:text-yellow-300"
        }`}>
          {t.inlineCards.interviewTitle}
        </span>
        {answered && (
          <span className="ml-auto text-[10px] text-green-600 dark:text-green-400">
            {t.inlineCards.answered}
          </span>
        )}
        {expired && (
          <span className="ml-auto text-[10px] text-slate-400">
            {t.inlineCards.expired}
          </span>
        )}
        {!disabled && (
          <span className="ml-auto text-[10px] text-yellow-600/70 dark:text-yellow-400/60">
            {t.inlineCards.pipelineWaiting}
          </span>
        )}
      </div>

      {/* Question */}
      <div className="px-3 py-2.5">
        <p className="text-sm text-slate-800 dark:text-slate-200 leading-relaxed font-medium">
          {question}
        </p>
      </div>

      {/* Answer display (answered state) */}
      {answered && (
        <div className="px-3 pb-3">
          <div className="bg-green-100/60 dark:bg-green-900/20 rounded-lg px-3 py-2
                          text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
            {answered}
          </div>
        </div>
      )}

      {/* Input (active state) */}
      {!disabled && (
        <div className="px-3 pb-3 space-y-2">
          <textarea
            ref={inputRef}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={t.inlineCards.answerPlaceholder}
            disabled={submitting}
            className="w-full bg-white dark:bg-slate-800 border border-stone-300 dark:border-slate-600
                       focus:border-yellow-500 dark:focus:border-yellow-500/60
                       rounded-lg px-3 py-2 text-sm text-slate-800 dark:text-slate-200
                       resize-none outline-none transition-colors
                       disabled:opacity-50 placeholder-slate-400 dark:placeholder-slate-500"
          />

          {error && <p className="text-red-500 text-[10px]">{error}</p>}

          <div className="flex items-center justify-between">
            <p className="text-[10px] text-slate-400 dark:text-slate-500">
              Ctrl+Enter
            </p>
            <button
              onClick={handleSubmit}
              disabled={submitting || !answer.trim()}
              className="text-xs px-3 py-1.5 rounded-lg font-medium transition-colors
                         bg-yellow-600 hover:bg-yellow-500 text-white
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {submitting ? t.inlineCards.submitting : t.inlineCards.submitAnswer}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
