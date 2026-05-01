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
        <h1 className="text-2xl font-bold text-white">Account Pending Approval</h1>
        <p className="text-slate-400 text-sm leading-relaxed">
          Your account is awaiting admin approval.
          <br />
          Once approved, you will have full access to all features.
        </p>
      </div>

      {/* User info */}
      {user && (
        <div className="bg-[#0d1526] border border-slate-700/50 rounded-xl px-5 py-4 text-left space-y-2">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Signed in as</p>
          <p className="text-sm text-white font-medium">{user.display_name || user.email}</p>
          <p className="text-xs text-slate-400">{user.email}</p>
          {user.tenant && (
            <p className="text-xs text-slate-500">
              Tenant: {user.tenant.name} ({user.tenant.plan})
            </p>
          )}
        </div>
      )}

      {/* Instructions */}
      <div className="bg-blue-900/20 border border-blue-700/30 rounded-xl px-5 py-4 text-left space-y-2">
        <p className="text-xs font-semibold text-blue-300">What to do next?</p>
        <ul className="text-xs text-slate-400 space-y-1 list-disc list-inside">
          <li>Contact your platform admin and provide your registered email address.</li>
          <li>After approval, refresh this page or log in again to get started.</li>
        </ul>
      </div>

      {/* Actions */}
      <div className="flex gap-3 justify-center">
        <button
          onClick={handleCheckStatus}
          className="px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium transition-colors"
        >
          Refresh Status
        </button>
        <button
          onClick={handleLogout}
          className="px-5 py-2.5 rounded-xl bg-red-900/30 hover:bg-red-900/50 border border-red-700/40 text-red-300 text-sm font-medium transition-colors"
        >
          Sign Out
        </button>
      </div>

      <p className="text-xs text-slate-600">AegisHarness · Account Approval</p>
    </div>
  );
}
