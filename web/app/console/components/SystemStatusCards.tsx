"use client";

interface JobStats {
  total: number;
  running: number;
  completed: number;
  failed: number;
  pending: number;
}

interface UserStats {
  total: number;
  active: number;
}

interface Props {
  jobs: JobStats;
  users: UserStats;
  tenantCount: number;
  activeTenantCount: number;
  totalCostUsd: number;
}

interface KpiCardProps {
  label: string;
  value: number | string;
  sub?: string;
  accent?: string;
}

function KpiCard({ label, value, sub, accent = "text-white" }: KpiCardProps) {
  return (
    <div className="bg-[#0d1526] border border-slate-700/50 rounded-xl px-5 py-4 flex flex-col gap-1">
      <span className="text-xs text-slate-400 uppercase tracking-wide">{label}</span>
      <span className={`text-3xl font-bold ${accent}`}>{value}</span>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </div>
  );
}

export function SystemStatusCards({ jobs, users, tenantCount, activeTenantCount, totalCostUsd }: Props) {
  const successRate = jobs.total > 0
    ? Math.round((jobs.completed / jobs.total) * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
      <KpiCard
        label="Total Jobs"
        value={jobs.total}
        sub={`${jobs.running} running · ${jobs.pending} pending`}
      />
      <KpiCard
        label="Completed"
        value={jobs.completed}
        sub={`Success rate ${successRate}%`}
        accent="text-emerald-400"
      />
      <KpiCard
        label="Failed"
        value={jobs.failed}
        accent={jobs.failed > 0 ? "text-red-400" : "text-white"}
      />
      <KpiCard
        label="Tenants"
        value={activeTenantCount}
        sub={`${tenantCount} total`}
        accent="text-blue-400"
      />
      <KpiCard
        label="Users"
        value={users.active}
        sub={`${users.total} total`}
        accent="text-violet-400"
      />
      <KpiCard
        label="Actual Cost"
        value={`$${totalCostUsd.toFixed(4)}`}
        sub="Cumulative USD"
        accent="text-amber-400"
      />
    </div>
  );
}
