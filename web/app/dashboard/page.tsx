"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { JobStatusBadge } from "@/components/JobStatusBadge";
import { useT } from "@/lib/i18n";

interface Job {
  id: string;
  type: string;
  workspace_id: string;
  requirement: string;
  status: string;
  created_at: string;
  event_count: number;
}

export default function DashboardPage() {
  const t = useT();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchJobs = async () => {
    setFetchError("");
    try {
      const res = await fetch("/api/proxy/jobs");
      if (res.ok) setJobs(await res.json());
    } catch {
      setFetchError(t.dashboard.loadError);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, jobId: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm(t.dashboard.deleteConfirm)) return;
    setDeletingId(jobId);
    try {
      const res = await fetch(`/api/proxy/jobs/${jobId}`, { method: "DELETE" });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        alert(t.dashboard.deleteFailed((j as { detail?: string }).detail ?? `HTTP ${res.status}`));
      } else {
        setJobs((prev) => prev.filter((j) => j.id !== jobId));
      }
    } catch (err) {
      alert(t.dashboard.deleteFailed(String(err)));
    } finally {
      setDeletingId(null);
    }
  };

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{t.dashboard.title}</h1>
          <p className="text-slate-400 text-sm mt-1">{t.dashboard.subtitle}</p>
        </div>
      </div>

      {fetchError && (
        <div className="bg-red-950/60 border border-red-800 rounded-xl px-4 py-3 flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <p className="text-red-300 text-sm font-medium">⚠️ {fetchError}</p>
            <p className="text-red-400/80 text-xs">{t.dashboard.backendHint}</p>
          </div>
          <button
            onClick={fetchJobs}
            className="px-3 py-1.5 text-xs bg-red-900/40 hover:bg-red-800/60 border border-red-700 text-red-300 rounded-lg transition-colors flex-shrink-0"
          >
            {t.dashboard.retryBtn}
          </button>
        </div>
      )}

      {/* Stats cards */}
      {!loading && (
        <div className="grid grid-cols-4 gap-4">
          {(
            [
              { label: t.dashboard.all, filter: () => true, color: "text-slate-300" },
              { label: t.dashboard.running, filter: (j: Job) => j.status === "running" || j.status === "waiting_approval", color: "text-blue-400" },
              { label: t.dashboard.completed, filter: (j: Job) => j.status === "completed", color: "text-green-400" },
              { label: t.dashboard.failedRejected, filter: (j: Job) => j.status === "failed" || j.status === "rejected", color: "text-red-400" },
            ] as const
          ).map(({ label, filter, color }) => (
            <div key={label} className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
              <div className={`text-2xl font-bold ${color}`}>
                {jobs.filter(filter as (j: Job) => boolean).length}
              </div>
              <div className="text-slate-400 text-sm">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Job list */}
      {loading ? (
        <div className="text-slate-400 text-center py-16">{t.dashboard.loading}</div>
      ) : jobs.length === 0 ? (
        <div className="text-center py-20 text-slate-500">
          <div className="text-4xl mb-4">📋</div>
          <p className="text-lg">{t.dashboard.noJobs}</p>
          <p className="text-sm mt-2 text-slate-600">
            Go to the AI Workspace and enter the <code className="text-violet-400">/task</code> command to submit a task
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <div key={job.id} className="relative group">
              <Link href={`/jobs/${job.id}`}>
                <div className="bg-slate-800/50 border border-slate-700 hover:border-slate-500 rounded-xl p-5 transition-all cursor-pointer">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2">
                        <span className="font-mono text-xs text-slate-500 bg-slate-900 px-2 py-0.5 rounded">
                          #{job.id.slice(0, 8)}
                        </span>
                        <span className="text-xs text-slate-400 uppercase tracking-wide">
                          {job.type === "update" ? t.dashboard.typeUpdate : t.dashboard.typeNew}
                        </span>
                        <span className="text-xs text-slate-500">{job.workspace_id}</span>
                      </div>
                      <p className="text-slate-200 text-sm truncate">{job.requirement}</p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-xs text-slate-500">
                        {t.dashboard.events(job.event_count)}
                      </span>
                      <JobStatusBadge status={job.status} />
                    </div>
                  </div>
                  <div className="mt-3 text-xs text-slate-500">
                    {new Date(job.created_at).toLocaleString("zh-CN")}
                  </div>
                </div>
              </Link>
              {/* Delete button — appears on row hover */}
              <button
                onClick={(e) => handleDelete(e, job.id)}
                disabled={deletingId === job.id}
                className="absolute top-3 right-3 opacity-0 group-hover:opacity-100
                           px-2 py-1 rounded-lg text-xs transition-all
                           text-red-400 hover:text-red-300 hover:bg-red-900/30
                           border border-transparent hover:border-red-800/50
                           disabled:opacity-40 disabled:cursor-not-allowed"
                title={t.dashboard.deleteBtn}
              >
                {deletingId === job.id ? t.dashboard.deleting : "🗑"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
