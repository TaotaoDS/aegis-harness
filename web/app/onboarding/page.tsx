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
      <div className="text-center text-slate-400 text-sm py-12">Checking system status…</div>
    );
  }

  if (step === "done") {
    return (
      <div className="text-center space-y-3 py-12">
        <div className="text-4xl">✅</div>
        <p className="text-white font-semibold text-lg">Super admin created successfully</p>
        <p className="text-slate-400 text-sm">Redirecting to the admin console…</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="text-4xl mb-4">⚙️</div>
        <h1 className="text-2xl font-bold text-white">System Setup Wizard</h1>
        <p className="text-slate-400 text-sm">
          Create the platform super-admin account to start managing tenants and users.
        </p>
      </div>

      {/* Info banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 text-xs text-amber-300 space-y-1">
        <p className="font-semibold">⚠ Keep these credentials safe</p>
        <p>The super-admin account has the highest platform privileges. This wizard is only available on first launch and will be permanently locked afterwards.</p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1">
          <label className="block text-xs text-slate-400 font-medium">Display Name (optional)</label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Super Admin"
            className="w-full bg-[#0d1526] border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <div className="space-y-1">
          <label className="block text-xs text-slate-400 font-medium">Email Address *</label>
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
          <label className="block text-xs text-slate-400 font-medium">Password *</label>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
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
          {submitting ? "Creating…" : "Create Super Admin Account"}
        </button>
      </form>

      <p className="text-center text-xs text-slate-600">
        AegisHarness · System Setup
      </p>
    </div>
  );
}
