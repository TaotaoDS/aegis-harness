"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/context";
import { listPendingUsers, approveUser } from "@/lib/auth/client";
import type { PendingUser } from "@/lib/auth/client";

export default function AdminPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  const [pendingUsers, setPendingUsers] = useState<PendingUser[]>([]);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [credits, setCredits] = useState<Record<string, string>>({});
  const [approving, setApproving] = useState<Record<string, boolean>>({});
  const [approved, setApproved] = useState<Record<string, boolean>>({});
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Auth guard — super_admin only
  useEffect(() => {
    if (!loading && user && user.role !== "super_admin") {
      router.replace("/");
    }
  }, [user, loading, router]);

  const loadUsers = useCallback(async () => {
    try {
      const users = await listPendingUsers();
      setPendingUsers(users);
      setFetchError(null);
      setLastRefresh(new Date());
    } catch (e: unknown) {
      setFetchError(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    if (!loading && user?.role === "super_admin") {
      loadUsers();
    }
  }, [loading, user, loadUsers]);

  async function handleApprove(userId: string) {
    setApproving((p) => ({ ...p, [userId]: true }));
    try {
      const creditStr = credits[userId];
      const creditAmount = creditStr ? parseFloat(creditStr) : undefined;
      await approveUser(userId, creditAmount);
      setApproved((p) => ({ ...p, [userId]: true }));
      // Remove from list after short delay
      setTimeout(() => {
        setPendingUsers((prev) => prev.filter((u) => u.id !== userId));
      }, 800);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproving((p) => ({ ...p, [userId]: false }));
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400">
        Loading…
      </div>
    );
  }
  if (!user || user.role !== "super_admin") return null;

  return (
    <main className="flex-1 overflow-y-auto bg-[#0a0f1e] px-6 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">User Approval</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {lastRefresh
              ? `Last refreshed: ${lastRefresh.toLocaleTimeString()}`
              : "Loading…"}
            {" · "}
            {pendingUsers.length} pending user(s)
          </p>
        </div>
        <button
          onClick={loadUsers}
          className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Error */}
      {fetchError && (
        <div className="bg-red-900/30 border border-red-700/50 rounded-lg px-4 py-2 text-sm text-red-300">
          Failed to load: {fetchError}
        </div>
      )}

      {/* Empty state */}
      {!fetchError && pendingUsers.length === 0 && (
        <div className="bg-[#0d1526] border border-slate-700/50 rounded-xl px-6 py-12 text-center">
          <div className="text-3xl mb-3">🎉</div>
          <p className="text-slate-300 font-medium">No pending users</p>
          <p className="text-slate-500 text-sm mt-1">New registrations will appear here awaiting your approval.</p>
        </div>
      )}

      {/* Pending users list */}
      {pendingUsers.length > 0 && (
        <div className="bg-[#0d1526] border border-slate-700/50 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 text-xs text-slate-400 uppercase tracking-wide">
                <th className="px-4 py-3 text-left">User</th>
                <th className="px-4 py-3 text-left">Tenant</th>
                <th className="px-4 py-3 text-left">Registered At</th>
                <th className="px-4 py-3 text-left w-36">Initial Credit (USD)</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {pendingUsers.map((u) => (
                <tr
                  key={u.id}
                  className={`transition-colors ${
                    approved[u.id] ? "bg-emerald-900/10" : "hover:bg-slate-800/30"
                  }`}
                >
                  <td className="px-4 py-3">
                    <p className="text-white font-medium">{u.display_name || u.email}</p>
                    <p className="text-slate-500 text-xs">{u.email}</p>
                  </td>
                  <td className="px-4 py-3">
                    {u.tenant ? (
                      <div>
                        <p className="text-slate-300">{u.tenant.name}</p>
                        <p className="text-slate-500 text-xs">{u.tenant.plan}</p>
                      </div>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    {u.created_at ? new Date(u.created_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      placeholder="Leave blank = unlimited"
                      value={credits[u.id] ?? ""}
                      onChange={(e) => setCredits((p) => ({ ...p, [u.id]: e.target.value }))}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-blue-500"
                    />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {approved[u.id] ? (
                      <span className="text-emerald-400 text-xs font-medium">✓ Approved</span>
                    ) : (
                      <button
                        onClick={() => handleApprove(u.id)}
                        disabled={approving[u.id]}
                        className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-medium transition-colors"
                      >
                        {approving[u.id] ? "Processing…" : "Approve"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
