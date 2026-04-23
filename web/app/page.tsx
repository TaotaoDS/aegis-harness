"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { JobStatusBadge } from "@/components/JobStatusBadge";

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
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

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
    try {
      const res = await fetch("/api/proxy/jobs");
      if (res.ok) setJobs(await res.json());
    } catch {
      // ignore
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
          <h1 className="text-2xl font-bold text-white">任务总览</h1>
          <p className="text-slate-400 text-sm mt-1">监控所有 Agent 任务的实时状态</p>
        </div>
        <Link
          href="/jobs/new"
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
        >
          <span>＋</span> 新建任务
        </Link>
      </div>

      {/* Stats cards */}
      {!loading && (
        <div className="grid grid-cols-4 gap-4">
          {(
            [
              { label: "全部", filter: () => true, color: "text-slate-300" },
              { label: "运行中", filter: (j: Job) => j.status === "running" || j.status === "waiting_approval", color: "text-blue-400" },
              { label: "已完成", filter: (j: Job) => j.status === "completed", color: "text-green-400" },
              { label: "失败/拒绝", filter: (j: Job) => j.status === "failed" || j.status === "rejected", color: "text-red-400" },
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
        <div className="text-slate-400 text-center py-16">加载中…</div>
      ) : jobs.length === 0 ? (
        <div className="text-center py-20 text-slate-500">
          <div className="text-4xl mb-4">📋</div>
          <p className="text-lg">还没有任务</p>
          <p className="text-sm mt-2">
            点击右上角「新建任务」开始你的第一个 AI 开发任务
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
                        {job.type === "update" ? "🔄 更新" : "🚀 新建"}
                      </span>
                      <span className="text-xs text-slate-500">{job.workspace_id}</span>
                    </div>
                    <p className="text-slate-200 text-sm truncate">{job.requirement}</p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs text-slate-500">
                      {job.event_count} 个事件
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
