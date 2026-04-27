"use client";

/**
 * TaskCard — generative UI component rendered inline inside the chat stream
 * when the user runs a /task command.
 *
 * Opens its own SSE connection to the job's event stream and updates in-place
 * as the pipeline progresses — no page navigation required.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useT } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type JobType = "build" | "update";

interface Props {
  jobId:       string;
  requirement: string;
  jobType:     JobType;
}

type Phase =
  | "queued"
  | "interview"
  | "planning"
  | "execution"
  | "qa"
  | "complete"
  | "failed"
  | "rejected";

interface LogEntry {
  text: string;
  key: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Ordered visible pipeline steps (last = terminal success)
const PIPELINE_STEPS: Phase[] = ["queued", "interview", "planning", "execution", "qa", "complete"];

// Pipeline phase from event type
const PHASE_FROM_EVENT: Record<string, Phase> = {
  "ceo.interview_question": "interview",
  "ceo.question":           "interview",
  "ceo.interview_complete": "planning",
  "ceo.plan_complete":      "execution",
  "pipeline.execution_start":    "execution",
  "pipeline.execution_complete": "qa",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TaskCard({ jobId, requirement, jobType }: Props) {
  const t = useT();
  const PHASE_LABELS = t.taskCard.phaseLabels;

  const [phase,     setPhase]     = useState<Phase>("queued");
  const [logs,      setLogs]      = useState<LogEntry[]>([]);
  const [fileCount, setFileCount] = useState(0);
  const [done,      setDone]      = useState(false);
  const logKeyRef = useRef(0);
  const esRef     = useRef<EventSource | null>(null);
  const doneRef   = useRef(false);

  const addLog = (text: string) => {
    const key = ++logKeyRef.current;
    setLogs((prev) => [...prev.slice(-4), { text, key }]);
  };

  useEffect(() => {
    const es = new EventSource(`/api/proxy/jobs/${jobId}/events`);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const { type, label, data = {} } = JSON.parse(e.data as string) as {
          type: string;
          label?: string;
          data?: Record<string, unknown>;
        };

        // Advance phase
        if (PHASE_FROM_EVENT[type]) {
          setPhase(PHASE_FROM_EVENT[type]);
        } else if (type === "pipeline.phase_change" && data.phase) {
          setPhase(data.phase as Phase);
        }

        // Log meaningful events
        if (type === "ceo.interview_question" || type === "ceo.question") {
          const q = (data.question as string | undefined)?.slice(0, 80) ?? "interview";
          addLog(t.taskCard.interviewQuestion(q));
        } else if (type === "architect.file_written") {
          setFileCount((n) => n + 1);
        } else if (type === "pipeline.complete") {
          setPhase("complete");
          doneRef.current = true;
          setDone(true);
          addLog(t.taskCard.completed);
          es.close();
        } else if (type === "pipeline.failed") {
          setPhase("failed");
          doneRef.current = true;
          setDone(true);
          addLog(t.taskCard.failedWith((data.error as string | undefined) ?? "task failed"));
          es.close();
        } else if (type === "pipeline.rejected") {
          setPhase("rejected");
          doneRef.current = true;
          setDone(true);
          addLog(t.taskCard.rejectedMsg);
          es.close();
        } else if (label) {
          addLog(label);
        }
      } catch {
        // ignore malformed frames
      }
    };

    es.onerror = () => {
      if (!doneRef.current) {
        es.close();
        esRef.current = null;
      }
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const isTerminal = phase === "complete" || phase === "failed" || phase === "rejected";
  const phaseIdx   = PIPELINE_STEPS.indexOf(phase);

  // Linear progress percentage: 0..100 across PIPELINE_STEPS
  const totalSteps = PIPELINE_STEPS.length - 1;   // queued ... complete
  const progressPct = isTerminal
    ? (phase === "complete" ? 100 : Math.max(15, (phaseIdx / totalSteps) * 100))
    : Math.max(8, ((phaseIdx + 0.5) / totalSteps) * 100);

  const cardAccent =
    phase === "complete"
      ? "border-green-300 bg-green-50 dark:border-green-700/40 dark:bg-green-900/10"
      : phase === "failed" || phase === "rejected"
        ? "border-red-300 bg-red-50 dark:border-red-700/40 dark:bg-red-900/10"
        : "border-violet-200 bg-white shadow-sm dark:border-violet-700/30 dark:bg-[#0d1526]/80 dark:shadow-none";

  const phaseColor =
    phase === "complete"
      ? "text-green-600 dark:text-green-400"
      : phase === "failed" || phase === "rejected"
        ? "text-red-600 dark:text-red-400"
        : "text-violet-700 dark:text-violet-300";

  const progressBarColor =
    phase === "complete"
      ? "bg-green-500"
      : phase === "failed" || phase === "rejected"
        ? "bg-red-500"
        : "bg-violet-500";

  // Cancel handler — closes our SSE subscription and marks done locally.
  // (A backend /cancel endpoint can be plumbed in later; this at least stops UI updates.)
  const handleCancel = () => {
    if (esRef.current) esRef.current.close();
    esRef.current = null;
    doneRef.current = true;
    setDone(true);
    setPhase("rejected");
    addLog(t.taskCard.cancelLog);
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className={`rounded-xl border ${cardAccent} overflow-hidden text-xs w-full transition-colors`}>

      {/* ── Header ── */}
      <div className="px-3 py-2 border-b border-stone-200/70 dark:border-slate-700/40
                      flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`shrink-0 px-1.5 py-0.5 rounded font-mono text-[10px] font-semibold ${
            jobType === "build"
              ? "bg-blue-100 text-blue-700 border border-blue-300 dark:bg-blue-900/50 dark:text-blue-300 dark:border-blue-700/40"
              : "bg-amber-100 text-amber-700 border border-amber-300 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-700/40"
          }`}>
            {jobType === "build" ? "BUILD" : "UPDATE"}
          </span>
          <span className="text-slate-800 dark:text-slate-200 truncate font-medium" title={requirement}>
            {requirement.length > 60 ? requirement.slice(0, 58) + "…" : requirement}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {!isTerminal && (
            <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" />
          )}
          <span className={`font-medium ${phaseColor}`}>
            {PHASE_LABELS[phase as keyof typeof PHASE_LABELS] ?? phase}
          </span>
        </div>
      </div>

      {/* ── Linear progress bar ── */}
      <div className="px-3 pt-2.5">
        <div className="w-full h-1.5 rounded-full overflow-hidden bg-stone-200 dark:bg-slate-700/60">
          <div
            className={`h-full rounded-full transition-all duration-500 ${progressBarColor} ${
              !isTerminal ? "animate-pulse" : ""
            }`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* ── Pipeline stepper (compact dots) ── */}
      <div className="px-3 pt-2 pb-1.5 flex items-center gap-0.5">
        {PIPELINE_STEPS.map((step, i) => {
          const reached = isTerminal
            ? (phase === "complete" || i < PIPELINE_STEPS.length - 1)
            : phaseIdx > i;
          const isCurrent = !isTerminal && phaseIdx === i;
          return (
            <div key={step} className="flex items-center gap-0.5">
              {i > 0 && (
                <div className={`w-4 h-px ${
                  reached || (isCurrent && i <= phaseIdx)
                    ? "bg-violet-500"
                    : "bg-stone-300 dark:bg-slate-700"
                }`} />
              )}
              <div
                title={PHASE_LABELS[step as keyof typeof PHASE_LABELS]}
                className={`w-2 h-2 rounded-full transition-colors ${
                  phase === "complete" && step === "complete"
                    ? "bg-green-500"
                    : isCurrent
                      ? "bg-violet-500 ring-2 ring-violet-400/40 animate-pulse"
                      : reached
                        ? "bg-violet-600"
                        : "bg-stone-300 dark:bg-slate-700"
                }`}
              />
            </div>
          );
        })}
        {fileCount > 0 && (
          <span className="ml-3 text-[10px] text-slate-500 dark:text-slate-500">
            {t.taskCard.filesGenerated(fileCount)}
          </span>
        )}
      </div>

      {/* ── Event log (last 3 entries) ── */}
      {logs.length > 0 && (
        <div className="px-3 pb-2 space-y-0.5">
          {logs.slice(-3).map((log) => (
            <div key={log.key}
                 className="text-[10px] text-slate-500 dark:text-slate-500 truncate leading-relaxed">
              {log.text}
            </div>
          ))}
        </div>
      )}

      {/* ── Footer ── */}
      <div className="px-3 py-1.5 border-t border-stone-200/70 dark:border-slate-800/40
                      flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-400 dark:text-slate-600 font-mono">
          #{jobId.slice(0, 8)}
        </span>
        <div className="flex items-center gap-2">
          {!isTerminal && (
            <button
              onClick={handleCancel}
              className="text-[10px] px-2 py-0.5 rounded
                         text-red-600 hover:text-red-700 hover:bg-red-50
                         dark:text-red-400 dark:hover:text-red-300 dark:hover:bg-red-900/20
                         transition-colors"
            >
              {t.taskCard.cancel}
            </button>
          )}
          <Link
            href={`/jobs/${jobId}`}
            className="text-[10px] text-blue-600 hover:text-blue-700
                       dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
          >
            {done ? t.taskCard.viewReport : t.taskCard.viewLive}
          </Link>
        </div>
      </div>
    </div>
  );
}
