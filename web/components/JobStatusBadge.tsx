"use client";

import { useT } from "@/lib/i18n";

export function JobStatusBadge({ status }: { status: string }) {
  const t = useT();

  const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
    pending: {
      label: t.status.pending,
      className: "bg-slate-700 text-slate-300",
    },
    running: {
      label: t.status.running,
      className: "bg-blue-900/50 text-blue-300 animate-pulse",
    },
    waiting_approval: {
      label: t.status.waiting_approval,
      className: "bg-yellow-900/50 text-yellow-300 animate-pulse",
    },
    completed: {
      label: t.status.completed,
      className: "bg-green-900/50 text-green-300",
    },
    failed: {
      label: t.status.failed,
      className: "bg-red-900/50 text-red-300",
    },
    rejected: {
      label: t.status.rejected,
      className: "bg-orange-900/50 text-orange-300",
    },
  };

  const FALLBACK = { label: t.status.unknown, className: "bg-slate-700 text-slate-400" };

  const cfg = STATUS_CONFIG[status] ?? FALLBACK;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${cfg.className}`}
    >
      {cfg.label}
    </span>
  );
}
