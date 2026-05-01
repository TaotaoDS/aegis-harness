"use client";

/**
 * Overlay modal shown when the proxy detects X-Auth-Expired: true.
 *
 * Renders a login form on top of the current page WITHOUT clearing any
 * in-memory state (chat history, graph selection, etc.) so the user can
 * re-authenticate and continue exactly where they left off.
 */

import { useState } from "react";
import { useAuth } from "@/lib/auth/context";
import { useT }   from "@/lib/i18n";

export function SessionExpiredModal() {
  const { login, clearSessionExpired } = useAuth();
  const t = useT();

  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      clearSessionExpired();
    } catch (err) {
      setError(err instanceof Error ? err.message : t.sessionExpired.loginFailed);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="w-full max-w-sm bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-8">
        <div className="text-center mb-6">
          <div className="text-3xl mb-2">🔐</div>
          <h2 className="text-lg font-semibold text-white">{t.sessionExpired.title}</h2>
          <p className="text-slate-400 text-sm mt-1">{t.sessionExpired.subtitle}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t.sessionExpired.email}</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2
                         text-sm text-white placeholder-slate-500 focus:outline-none
                         focus:border-violet-500 focus:ring-1 focus:ring-violet-500"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">{t.sessionExpired.password}</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2
                         text-sm text-white placeholder-slate-500 focus:outline-none
                         focus:border-violet-500 focus:ring-1 focus:ring-violet-500"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="text-red-400 text-xs">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 rounded-lg text-sm font-medium transition-colors
                       bg-violet-600 hover:bg-violet-500 text-white
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? t.sessionExpired.signingIn : t.sessionExpired.signIn}
          </button>
        </form>
      </div>
    </div>
  );
}
