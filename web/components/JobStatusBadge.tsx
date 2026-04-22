const STATUS_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  pending: {
    label: "等待中",
    className: "bg-slate-700 text-slate-300",
  },
  running: {
    label: "运行中",
    className: "bg-blue-900/50 text-blue-300 animate-pulse",
  },
  waiting_approval: {
    label: "等待审批",
    className: "bg-yellow-900/50 text-yellow-300 animate-pulse",
  },
  completed: {
    label: "已完成",
    className: "bg-green-900/50 text-green-300",
  },
  failed: {
    label: "已失败",
    className: "bg-red-900/50 text-red-300",
  },
  rejected: {
    label: "已拒绝",
    className: "bg-orange-900/50 text-orange-300",
  },
};

const FALLBACK = { label: "未知", className: "bg-slate-700 text-slate-400" };

export function JobStatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? FALLBACK;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cfg.className}`}
    >
      {cfg.label}
    </span>
  );
}
