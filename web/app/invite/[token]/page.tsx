"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useParams } from "next/navigation";
import { acceptInvite } from "@/lib/auth/client";
import { useAuth } from "@/lib/auth/context";
import { useT } from "@/lib/i18n";

export default function InvitePage() {
  const t = useT();
  const { refresh } = useAuth();
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const token = params.token ?? "";

  const [password, setPassword]       = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError]             = useState("");
  const [loading, setLoading]         = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");

    if (password.length < 8) {
      setError(t.auth.passwordMinLength);
      return;
    }

    setLoading(true);
    try {
      await acceptInvite(token, password, displayName || undefined);
      await refresh();
      router.replace("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t.auth.acceptInviteError);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-[#060d1a]">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 text-center">
          <span className="text-3xl">⚙️</span>
          <h1 className="mt-2 text-xl font-bold text-white">AegisHarness</h1>
        </div>

        <div className="bg-[#0d1526] border border-slate-800 rounded-xl p-8 shadow-xl">
          <h2 className="text-lg font-semibold text-white mb-1">{t.auth.inviteTitle}</h2>
          <p className="text-sm text-slate-400 mb-6">{t.auth.inviteSubtitle}</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                {t.auth.displayNameLabel}
              </label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder={t.auth.displayNamePlaceholder}
                className="w-full px-3 py-2 rounded-lg bg-[#060d1a] border border-slate-700 text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                {t.auth.passwordLabel}
              </label>
              <input
                type="password"
                required
                autoComplete="new-password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-[#060d1a] border border-slate-700 text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500"
              />
              <p className="mt-1 text-xs text-slate-500">{t.auth.passwordMinLength}</p>
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
            >
              {loading ? t.auth.acceptInviteLoading : t.auth.acceptInviteBtn}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
