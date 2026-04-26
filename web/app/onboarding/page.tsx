"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { checkSetupStatus, setupSuperAdmin } from "@/lib/auth/client";
import { useAuth } from "@/lib/auth/context";

type Step = "check" | "form" | "done";

export default function OnboardingPage() {
  const router = useRouter();
  const { refresh } = useAuth();

  const [step, setStep] = useState<Step>("check");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // On mount: if already initialised, send to login
  useEffect(() => {
    checkSetupStatus().then((initialized) => {
      if (initialized) {
        router.replace("/login");
      } else {
        setStep("form");
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await setupSuperAdmin({ email, password, display_name: displayName || undefined });
      await refresh();
      setStep("done");
      setTimeout(() => router.replace("/admin"), 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Setup failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (step === "check") {
    return (
      <div className="text-center text-slate-400 text-sm py-12">检测系统状态…</div>
    );
  }

  if (step === "done") {
    return (
      <div className="text-center space-y-3 py-12">
        <div className="text-4xl">✅</div>
        <p className="text-white font-semibold text-lg">超级管理员创建成功</p>
        <p className="text-slate-400 text-sm">正在跳转到管理控制台…</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="text-4xl mb-4">⚙️</div>
        <h1 className="text-2xl font-bold text-white">系统初始化向导</h1>
        <p className="text-slate-400 text-sm">
          创建平台超级管理员账号，完成后即可开始管理租户和用户。
        </p>
      </div>

      {/* Info banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 text-xs text-amber-300 space-y-1">
        <p className="font-semibold">⚠ 请妥善保管此账号凭据</p>
        <p>超级管理员拥有平台最高权限，此向导仅在系统首次启动时可用，之后永久锁定。</p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1">
          <label className="block text-xs text-slate-400 font-medium">显示名称（可选）</label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Super Admin"
            className="w-full bg-[#0d1526] border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <div className="space-y-1">
          <label className="block text-xs text-slate-400 font-medium">邮箱地址 *</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@example.com"
            className="w-full bg-[#0d1526] border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <div className="space-y-1">
          <label className="block text-xs text-slate-400 font-medium">登录密码 *</label>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="至少 8 位字符"
            className="w-full bg-[#0d1526] border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-3 py-2 text-xs text-red-300">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm transition-colors"
        >
          {submitting ? "创建中…" : "创建超级管理员账号"}
        </button>
      </form>

      <p className="text-center text-xs text-slate-600">
        AegisHarness · 系统初始化
      </p>
    </div>
  );
}
