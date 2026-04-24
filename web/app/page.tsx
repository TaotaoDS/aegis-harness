"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  const router = useRouter();
  const t = useT();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState("");

  // ── Onboarding check ───────────────────────────────────────────────────
  // If the user has never configured API keys (and hasn't skipped onboarding),
  // redirect to the setup wizard on first load.
  useEffect(() => {
    (async () => {
      try {
        const [keysRes, onboardedRes] = await Promise.all([
          fetch("/api/proxy/settings/api_keys"),
          fetch("/api/proxy/settings/onboarded"),
        ]);
        const keysData = keysRes.ok ? await keysRes.json() : null;
        const onboardedData = onboardedRes.ok ? await onboardedRes.json() : null;

        const hasKeys =
          keysData?.value &&
          typeof keysData.value === "object" &&
          Object.keys(keysData.value).length > 0;
        const alreadyOnboarded = onboardedData?.value === true;

        if (!hasKeys && !alreadyOnboarded) {
          router.replace("/onboarding");
        }
      } catch {
        // Backend not reachable — stay on dashboard, don't redirect
      }
    })();
  }, [router]);
  // ────────────────────────────────────────────────────────────────────────

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

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{t.dashboard.title}</h1>
          <p className="text-slate-400 text-sm mt-1">{t.dashboard.subtitle}</p>
        </div>
        <Link
          href="/jobs/new"
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
        >
          <span>＋</span> {t.dashboard.newJob}
        </Link>
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
          <p className="text-sm mt-2">
            {t.dashboard.noJobsHint}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {jobs.map((job) => (
            <Link key={job.id} href={`/jobs/${job.id}`}>
              <div className="bg-slate-800/50 border border-slate-700 hover:border-slate-500 rounded-xl p-5 transition-all cursor-pointer">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-2">
                      <span className="font-mono text-xs text-slate-500 bg-slate-900 px-2 py-0.5 rounded">
                        #{job.id}
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
          ))}
        </div>
      )}
    </div>
  );
}
