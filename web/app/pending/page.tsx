"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { logout } from "@/lib/auth/client";

export default function PendingPage() {
  const { user, refresh } = useAuth();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  async function handleCheckStatus() {
    await refresh();
    // Shell will handle the redirect if status changed to active
  }

  return (
    <div className="text-center space-y-6">
      {/* Icon */}
      <div className="w-20 h-20 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto">
        <span className="text-4xl">⏳</span>
      </div>

      {/* Title */}
      <div className="space-y-2">
        <h1 className="text-2xl font-bold text-white">账号审核中</h1>
        <p className="text-slate-400 text-sm leading-relaxed">
          您的账号正在等待管理员审批。
          <br />
          审批通过后，您将可以正常使用所有功能。
        </p>
      </div>

      {/* User info */}
      {user && (
        <div className="bg-[#0d1526] border border-slate-700/50 rounded-xl px-5 py-4 text-left space-y-2">
          <p className="text-xs text-slate-500 uppercase tracking-wide">已登录账号</p>
          <p className="text-sm text-white font-medium">{user.display_name || user.email}</p>
          <p className="text-xs text-slate-400">{user.email}</p>
          {user.tenant && (
            <p className="text-xs text-slate-500">
              租户：{user.tenant.name}（{user.tenant.plan}）
            </p>
          )}
        </div>
      )}

      {/* Instructions */}
      <div className="bg-blue-900/20 border border-blue-700/30 rounded-xl px-5 py-4 text-left space-y-2">
        <p className="text-xs font-semibold text-blue-300">接下来怎么做？</p>
        <ul className="text-xs text-slate-400 space-y-1 list-disc list-inside">
          <li>联系您的平台管理员，提供您的注册邮箱。</li>
          <li>管理员审批后，刷新此页面或重新登录即可使用。</li>
        </ul>
      </div>

      {/* Actions */}
      <div className="flex gap-3 justify-center">
        <button
          onClick={handleCheckStatus}
          className="px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium transition-colors"
        >
          刷新状态
        </button>
        <button
          onClick={handleLogout}
          className="px-5 py-2.5 rounded-xl bg-red-900/30 hover:bg-red-900/50 border border-red-700/40 text-red-300 text-sm font-medium transition-colors"
        >
          退出登录
        </button>
      </div>

      <p className="text-xs text-slate-600">AegisHarness · 账号审核</p>
    </div>
  );
}
