"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { StreamEvent } from "@/hooks/useEventStream";
import { useT } from "@/lib/i18n";

interface Props {
  events: StreamEvent[];
  finalStatus: string; // "completed" | "failed" | "rejected"
}

const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  failed:    "#ef4444",
  rejected:  "#f97316",
};

/** Count how many events belong to each top-level agent category. */
function buildChartData(events: StreamEvent[]) {
  const counts: Record<string, number> = {
    CEO:        0,
    Architect:  0,
    Evaluator:  0,
    QA:         0,
    Resilience: 0,
    HITL:       0,
    Other:      0,
  };

  for (const e of events) {
    if (e.type.startsWith("ceo."))        counts.CEO++;
    else if (e.type.startsWith("architect.")) counts.Architect++;
    else if (e.type.startsWith("evaluator.")) counts.Evaluator++;
    else if (e.type.startsWith("qa."))        counts.QA++;
    else if (e.type.startsWith("resilience.")) counts.Resilience++;
    else if (e.type.startsWith("hitl."))      counts.HITL++;
    else                                      counts.Other++;
  }

  return Object.entries(counts)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({ name, value }));
}

const CHART_FILL = "#3b82f6";

/**
 * Renders a summary dashboard once the pipeline reaches a terminal state.
 * Shows a bar chart of agent event distribution.
 */
export function SummaryDashboard({ events, finalStatus }: Props) {
  const t = useT();
  const chartData  = buildChartData(events);
  const color      = STATUS_COLORS[finalStatus] ?? "#64748b";
  const statusLabel =
    finalStatus === "completed"
      ? t.components.summary.completed
      : finalStatus === "rejected"
      ? t.components.summary.rejected
      : t.components.summary.failed;

  const filesWritten = events.filter((e) => e.type === "architect.file_written").length;
  const attempts     = events.filter((e) => e.type === "resilience.attempt_start").length;

  return (
    <div className="border rounded-2xl overflow-hidden" style={{ borderColor: color + "40" }}>
      {/* Header */}
      <div
        className="px-5 py-4"
        style={{ background: color + "15" }}
      >
        <h3 className="text-lg font-bold" style={{ color }}>
          {statusLabel}
        </h3>
        <p className="text-slate-400 text-sm mt-0.5">
          {t.components.summary.events(events.length)}
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 divide-x divide-slate-700 border-t border-slate-700">
        {[
          { label: t.components.summary.filesWritten, value: filesWritten },
          { label: t.components.summary.totalEvents, value: events.length },
          { label: t.components.summary.retries, value: Math.max(0, attempts - 1) },
        ].map(({ label, value }) => (
          <div key={label} className="px-5 py-3 text-center">
            <div className="text-2xl font-bold text-white">{value}</div>
            <div className="text-slate-400 text-xs">{label}</div>
          </div>
        ))}
      </div>

      {/* Chart */}
      {chartData.length > 0 && (
        <div className="px-5 py-4 border-t border-slate-700">
          <p className="text-slate-400 text-xs mb-3">{t.components.summary.distribution}</p>
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={chartData} barSize={28}>
              <XAxis
                dataKey="name"
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis hide />
              <Tooltip
                contentStyle={{
                  background: "#1e293b",
                  border: "1px solid #334155",
                  borderRadius: 8,
                  color: "#e2e8f0",
                  fontSize: 12,
                }}
                cursor={{ fill: "rgba(255,255,255,0.04)" }}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {chartData.map((_, idx) => (
                  <Cell
                    key={idx}
                    fill={idx % 2 === 0 ? CHART_FILL : "#6366f1"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
