"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

import { useEventStream }    from "@/hooks/useEventStream";
import { useApproval }       from "@/hooks/useApproval";
import { Timeline }          from "@/components/Timeline";
import { ApprovalModal }     from "@/components/ApprovalModal";
import { JobStatusBadge }    from "@/components/JobStatusBadge";
import { SummaryDashboard }  from "@/components/generative/SummaryDashboard";
import { HITL_EVENTS, TERMINAL_EVENTS } from "@/lib/eventLabels";
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
}

export default function JobDetailPage() {
  const { id }  = useParams<{ id: string }>();
  const router  = useRouter();

  const [job, setJob]         = useState<JobDetail | null>(null);
  const [jobError, setJobError] = useState("");

  // SSE event stream
  const { events, connected, done } = useEventStream(id);

  // HITL approval state
  const { pending, submitting, setPending, respond } = useApproval(id);

  // ── Fetch job metadata ──────────────────────────────────────────────────────
  useEffect(() => {
    const fetchJob = async () => {
      try {
        const res = await fetch(`/api/proxy/jobs/${id}`);
        if (res.status === 404) {
          setJobError("找不到该任务");
          return;
        }
        if (!res.ok) return;
        setJob(await res.json());
      } catch {
        setJobError("无法连接到后端服务");
      }
    };

    fetchJob();
    // Poll job status while not done (badge + pending_approval field)
    const interval = setInterval(() => {
      if (!done) fetchJob();
    }, 2000);
    return () => clearInterval(interval);
  }, [id, done]);

  // ── React to incoming stream events ────────────────────────────────────────
  useEffect(() => {
    const latest = events[events.length - 1];
    if (!latest) return;

    // Update job status optimistically from stream
    if (job) {
      const newStatus = deriveStatus(latest.type, job.status);
      if (newStatus !== job.status) {
        setJob((j) => j ? { ...j, status: newStatus } : j);
      }
    }

    // Open approval modal
    if (HITL_EVENTS.has(latest.type)) {
      const data = latest.data as Record<string, unknown>;
      setPending({
        reason:           (data.reason      as string) ?? "unknown",
        description:      (data.description as string) ?? "请审批此操作",
        files_to_modify:  (data.files_to_modify as string[]) ?? undefined,
        requirement:      (data.requirement as string) ?? undefined,
        filepath:         (data.filepath    as string) ?? undefined,
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length]);

  // ── Helpers ─────────────────────────────────────────────────────────────────
  const finalStatus = job?.status ?? "pending";
  const showSummary = done && TERMINAL_EVENTS.has(events[events.length - 1]?.type ?? "");

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
    return (
      <div className="max-w-3xl mx-auto text-center py-24 text-slate-400">
        加载中…
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* ── HITL Approval Modal ─────────────────────────────────────────── */}
      {pending && (
        <ApprovalModal
          pending={pending}
          submitting={submitting}
          onRespond={respond}
        />
      )}

      {/* ── Header ──────────────────────────────────────────────────────── */}
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
            <h1 className="text-xl font-bold text-white leading-snug">
              {job.requirement}
            </h1>
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

      {/* ── Live indicator / done badge ──────────────────────────────────── */}
      <div className="flex items-center gap-2 text-sm">
        {!done ? (
          <>
            <span className={`w-2 h-2 rounded-full live-dot ${
              connected ? "bg-green-500" : "bg-yellow-500"
            }`} />
            <span className="text-slate-400">
              {connected ? "实时监控中…" : "重连中…"}
            </span>
          </>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-slate-600" />
            <span className="text-slate-500">
              已完成 · 共 {events.length} 个事件
            </span>
          </>
        )}
      </div>

      {/* ── Summary dashboard (shown on completion) ─────────────────────── */}
      {showSummary && (
        <SummaryDashboard events={events} finalStatus={finalStatus} />
      )}

      {/* ── Event timeline ──────────────────────────────────────────────── */}
      <div className="bg-slate-800/40 border border-slate-700 rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-slate-300 mb-4">执行日志</h2>
        <Timeline events={events} autoScroll={!done} />
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Derive optimistic job status from the latest SSE event type. */
function deriveStatus(eventType: string, current: string): string {
  if (eventType === "pipeline.complete")           return "completed";
  if (eventType === "pipeline.error")              return "failed";
  if (eventType === "pipeline.rejected")           return "rejected";
  if (eventType === "hitl.approval_required")      return "waiting_approval";
  if (eventType === "hitl.approved" || eventType === "hitl.rejected") return "running";
  if (eventType === "pipeline.start")              return "running";
  return current;
}
