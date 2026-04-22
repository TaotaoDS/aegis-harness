"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

import { useEventStream }    from "@/hooks/useEventStream";
import { useApproval }       from "@/hooks/useApproval";
import { Timeline }          from "@/components/Timeline";
import { ApprovalModal }     from "@/components/ApprovalModal";
import { InterviewPanel }    from "@/components/InterviewPanel";
import { JobStatusBadge }    from "@/components/JobStatusBadge";
import { SummaryDashboard }  from "@/components/generative/SummaryDashboard";
import {
  HITL_EVENTS,
  INTERVIEW_EVENTS,
  INTERVIEW_DONE_EVENTS,
  TERMINAL_EVENTS,
} from "@/lib/eventLabels";
import type { PendingApproval } from "@/hooks/useApproval";

interface JobDetail {
  id: string;
  type: string;
  workspace_id: string;
  requirement: string;
  status: string;
  created_at: string;
  event_count: number;
  pending_approval: PendingApproval | null;
  pending_question: string | null;
}

export default function JobDetailPage() {
  const { id }  = useParams<{ id: string }>();
  const router  = useRouter();

  const [job,      setJob]      = useState<JobDetail | null>(null);
  const [jobError, setJobError] = useState("");

  // SSE event stream
  const { events, connected, done } = useEventStream(id);

  // HITL approval state
  const { pending: pendingApproval, submitting: approvalSubmitting,
          setPending: setApprovalPending, respond: respondApproval } = useApproval(id);

  // CEO interview state
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);

  // ── Fetch job metadata ─────────────────────────────────────────────────
  useEffect(() => {
    const fetchJob = async () => {
      try {
        const res = await fetch(`/api/proxy/jobs/${id}`);
        if (res.status === 404) { setJobError("找不到该任务"); return; }
        if (!res.ok) return;
        const j: JobDetail = await res.json();
        setJob(j);
        // Restore interview panel on page refresh if a question is pending
        if (j.pending_question && !pendingQuestion) {
          setPendingQuestion(j.pending_question);
        }
      } catch {
        setJobError("无法连接到后端服务");
      }
    };

    fetchJob();
    const interval = setInterval(() => { if (!done) fetchJob(); }, 2_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, done]);

  // ── React to incoming stream events ────────────────────────────────────
  useEffect(() => {
    const latest = events[events.length - 1];
    if (!latest) return;

    // Optimistic job-status update
    if (job) {
      const newStatus = deriveStatus(latest.type, job.status);
      if (newStatus !== job.status) setJob(j => j ? { ...j, status: newStatus } : j);
    }

    // CEO interview: show / hide the input panel
    if (INTERVIEW_EVENTS.has(latest.type)) {
      const q = (latest.data as Record<string, unknown>).question as string ?? "";
      if (q) setPendingQuestion(q);
    }
    if (INTERVIEW_DONE_EVENTS.has(latest.type)) {
      setPendingQuestion(null);
    }

    // HITL approval modal
    if (HITL_EVENTS.has(latest.type)) {
      const d = latest.data as Record<string, unknown>;
      setApprovalPending({
        reason:          (d.reason          as string) ?? "unknown",
        description:     (d.description     as string) ?? "请审批此操作",
        files_to_modify: (d.files_to_modify as string[]) ?? undefined,
        requirement:     (d.requirement     as string) ?? undefined,
        filepath:        (d.filepath        as string) ?? undefined,
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length]);

  // ── Derived state ──────────────────────────────────────────────────────
  const finalStatus = job?.status ?? "pending";
  const showSummary = done && TERMINAL_EVENTS.has(events[events.length - 1]?.type ?? "");

  // ── Error / loading ────────────────────────────────────────────────────
  if (jobError) {
    return (
      <div className="max-w-3xl mx-auto text-center py-24">
        <div className="text-5xl mb-4">🔍</div>
        <p className="text-slate-400 text-lg">{jobError}</p>
        <Link href="/" className="mt-6 inline-block text-blue-400 hover:text-blue-300 text-sm">
          ← 返回总览
        </Link>
      </div>
    );
  }

  if (!job) {
    return <div className="max-w-3xl mx-auto text-center py-24 text-slate-400">加载中…</div>;
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">

      {/* ── HITL Approval Modal ───────────────────────────────────────────── */}
      {pendingApproval && (
        <ApprovalModal
          pending={pendingApproval}
          submitting={approvalSubmitting}
          onRespond={respondApproval}
        />
      )}

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <button
            onClick={() => router.push("/")}
            className="text-slate-500 hover:text-slate-300 text-sm transition-colors"
          >
            ← 返回
          </button>
          <span className="text-slate-600">/</span>
          <span className="font-mono text-sm text-slate-400">#{id}</span>
        </div>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-bold text-white leading-snug">{job.requirement}</h1>
            <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
              <span>{job.type === "update" ? "🔄 迭代更新" : "🚀 全新构建"}</span>
              <span>·</span>
              <span>workspace: {job.workspace_id}</span>
              <span>·</span>
              <span>{new Date(job.created_at).toLocaleString("zh-CN")}</span>
            </div>
          </div>
          <JobStatusBadge status={finalStatus} />
        </div>
      </div>

      {/* ── Live / done indicator ─────────────────────────────────────────── */}
      <div className="flex items-center gap-2 text-sm">
        {!done ? (
          <>
            <span className={`w-2 h-2 rounded-full live-dot ${connected ? "bg-green-500" : "bg-yellow-500"}`} />
            <span className="text-slate-400">{connected ? "实时监控中…" : "重连中…"}</span>
          </>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-slate-600" />
            <span className="text-slate-500">已完成 · 共 {events.length} 个事件</span>
          </>
        )}
      </div>

      {/* ── CEO Interview Panel (shown when CEO is asking a question) ────── */}
      {pendingQuestion && !done && (
        <InterviewPanel
          jobId={id}
          question={pendingQuestion}
          onAnswered={() => setPendingQuestion(null)}
        />
      )}

      {/* ── Summary dashboard (shown on completion) ──────────────────────── */}
      {showSummary && (
        <SummaryDashboard events={events} finalStatus={finalStatus} />
      )}

      {/* ── Event timeline ────────────────────────────────────────────────── */}
      <div className="bg-slate-800/40 border border-slate-700 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-4">执行日志</h2>
        <Timeline events={events} autoScroll={!done} />
      </div>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

function deriveStatus(eventType: string, current: string): string {
  if (eventType === "pipeline.complete")           return "completed";
  if (eventType === "pipeline.error")              return "failed";
  if (eventType === "pipeline.rejected")           return "rejected";
  if (eventType === "hitl.approval_required")      return "waiting_approval";
  if (eventType === "hitl.approved" ||
      eventType === "hitl.rejected")               return "running";
  if (eventType === "pipeline.start")              return "running";
  if (eventType === "ceo.interviewing")            return "running";
  return current;
}
