"use client";

interface Tenant {
  id: string;
  name: string;
  plan: string;
  created_at: string;
  job_count: number;
}

interface Props {
  tenants: Tenant[];
}

const PLAN_BADGE: Record<string, string> = {
  free:       "bg-slate-700 text-slate-300",
  pro:        "bg-blue-500/20 text-blue-300",
  enterprise: "bg-amber-500/20 text-amber-300",
};

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  } catch {
    return iso?.slice(0, 10) ?? "—";
  }
}

export function TenantStatsPanel({ tenants }: Props) {
  const maxJobs = Math.max(...tenants.map((t) => t.job_count), 1);

  return (
    <div className="bg-[#0d1526] border border-slate-700/50 rounded-xl p-5">
      <h2 className="text-sm font-semibold text-white mb-4">租户列表</h2>

      {tenants.length === 0 ? (
        <p className="text-slate-500 text-sm">暂无租户数据</p>
      ) : (
        <div className="space-y-3">
          {tenants.map((t) => (
            <div key={t.id} className="flex items-center gap-3">
              {/* Name + plan */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm text-white truncate font-medium">{t.name}</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
                      PLAN_BADGE[t.plan] ?? "bg-slate-700 text-slate-300"
                    }`}
                  >
                    {t.plan}
                  </span>
                </div>
                {/* Progress bar */}
                <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all"
                    style={{ width: `${Math.round((t.job_count / maxJobs) * 100)}%` }}
                  />
                </div>
              </div>
              {/* Job count + date */}
              <div className="text-right shrink-0">
                <div className="text-sm font-semibold text-white">{t.job_count}</div>
                <div className="text-[10px] text-slate-500">{formatDate(t.created_at)}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
