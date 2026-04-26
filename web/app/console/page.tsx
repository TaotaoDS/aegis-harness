"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { SystemStatusCards } from "./components/SystemStatusCards";
import { TenantStatsPanel } from "./components/TenantStatsPanel";
import { TrendChart } from "./components/TrendChart";

type Range = "1h" | "6h" | "24h" | "7d";

interface ConsoleStats {
  jobs: { total: number; running: number; completed: number; failed: number; pending: number };
  users: { total: number; active: number };
  tenants: { total: number; active: number; list: Tenant[] };
  generated_at: string;
}

interface Tenant {
  id: string;
  name: string;
  plan: string;
  created_at: string;
  job_count: number;
}

interface TrendPoint {
  time: string;
  jobs: number;
  completed: number;
  failed: number;
}

const POLL_INTERVAL = 30_000;

async function fetchStats(): Promise<ConsoleStats> {
  const res = await fetch("/api/proxy/console/stats", { credentials: "include" });
  if (!res.ok) throw new Error(`stats ${res.status}`);
  return res.json();
}

async function fetchTrends(range: Range): Promise<TrendPoint[]> {
  const res = await fetch(`/api/proxy/console/trends?range=${range}`, { credentials: "include" });
  if (!res.ok) throw new Error(`trends ${res.status}`);
  const body = await res.json();
  return body.data ?? [];
}

export default function ConsolePage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  const [stats, setStats]           = useState<ConsoleStats | null>(null);
  const [trends, setTrends]         = useState<TrendPoint[]>([]);
  const [range, setRange]           = useState<Range>("24h");
  const [statsError, setStatsError] = useState<string | null>(null);
  const [trendLoading, setTrendLoading] = useState(false);
  const [lastRefresh, setLastRefresh]   = useState<Date | null>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Auth guard ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!authLoading && user && user.role !== "owner" && user.role !== "admin") {
      router.replace("/");
    }
  }, [user, authLoading, router]);

  // ── Data loaders ────────────────────────────────────────────────────────
  const loadStats = useCallback(async () => {
    try {
      const s = await fetchStats();
      setStats(s);
      setStatsError(null);
      setLastRefresh(new Date());
    } catch (e: unknown) {
      setStatsError(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  const loadTrends = useCallback(async (r: Range) => {
    setTrendLoading(true);
    try {
      const d = await fetchTrends(r);
      setTrends(d);
    } catch {
      setTrends([]);
    } finally {
      setTrendLoading(false);
    }
  }, []);

  // ── Initial load + 30s polling ──────────────────────────────────────────
  useEffect(() => {
    if (authLoading || !user) return;

    loadStats();
    loadTrends(range);

    intervalRef.current = setInterval(() => {
      if (!document.hidden) loadStats();
    }, POLL_INTERVAL);

    const onVisible = () => {
      if (!document.hidden) loadStats();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, user]);

  // ── Re-fetch trends on range change ────────────────────────────────────
  useEffect(() => {
    if (!authLoading && user) loadTrends(range);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  // ── Role-check gate ─────────────────────────────────────────────────────
  if (authLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400">
        加载中…
      </div>
    );
  }
  if (!user || (user.role !== "owner" && user.role !== "admin")) {
    return null;
  }

  return (
    <main className="flex-1 overflow-y-auto bg-[#0a0f1e] px-6 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">控制台看板</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {lastRefresh
              ? `上次刷新：${lastRefresh.toLocaleTimeString("zh-CN")} · 每 30 秒自动更新`
              : "加载中…"}
          </p>
        </div>
        <button
          onClick={() => { loadStats(); loadTrends(range); }}
          className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
        >
          刷新
        </button>
      </div>

      {/* Error banner */}
      {statsError && (
        <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-2 text-sm text-red-300">
          数据加载失败：{statsError}
        </div>
      )}

      {/* KPI cards */}
      {stats ? (
        <SystemStatusCards
          jobs={stats.jobs}
          users={stats.users}
          tenantCount={stats.tenants.total}
          activeTenantCount={stats.tenants.active}
        />
      ) : (
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="bg-[#0d1526] border border-slate-700/50 rounded-xl h-24 animate-pulse" />
          ))}
        </div>
      )}

      {/* Bottom row: tenant list + trend chart */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <TenantStatsPanel tenants={stats?.tenants.list ?? []} />
        <TrendChart
          data={trends}
          range={range}
          onRangeChange={setRange}
          loading={trendLoading}
        />
      </div>
    </main>
  );
}
