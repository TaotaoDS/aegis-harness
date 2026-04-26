"use client";

import { useState } from "react";
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";

type Range = "1h" | "6h" | "24h" | "7d";

interface DataPoint {
  time: string;
  jobs: number;
  completed: number;
  failed: number;
}

interface Props {
  data: DataPoint[];
  range: Range;
  onRangeChange: (r: Range) => void;
  loading?: boolean;
}

const RANGES: { key: Range; label: string }[] = [
  { key: "1h", label: "1h" },
  { key: "6h", label: "6h" },
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
];

function formatTime(iso: string, range: Range): string {
  try {
    const d = new Date(iso);
    if (range === "7d") return `${d.getMonth() + 1}/${d.getDate()}`;
    if (range === "24h") return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export function TrendChart({ data, range, onRangeChange, loading }: Props) {
  const chartData = data.map((d) => ({
    ...d,
    label: formatTime(d.time, range),
  }));

  return (
    <div className="bg-[#0d1526] border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-white">API 调用趋势</h2>
        <div className="flex gap-1">
          {RANGES.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => onRangeChange(key)}
              className={`px-2.5 py-1 text-xs rounded transition-colors ${
                range === key
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:text-white hover:bg-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
          加载中…
        </div>
      ) : chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
          暂无数据
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="label"
              tick={{ fill: "#64748b", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: "#64748b", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{ background: "#0d1526", border: "1px solid #334155", borderRadius: 8 }}
              labelStyle={{ color: "#94a3b8", fontSize: 12 }}
              itemStyle={{ fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: "#94a3b8" }} />
            <Bar dataKey="jobs" name="提交" fill="#3b82f6" radius={[3, 3, 0, 0]} maxBarSize={24} />
            <Line
              type="monotone"
              dataKey="completed"
              name="完成"
              stroke="#10b981"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="failed"
              name="失败"
              stroke="#f87171"
              strokeWidth={2}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
