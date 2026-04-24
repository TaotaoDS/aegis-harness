"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useT } from "@/lib/i18n";

export default function NewJobPage() {
  const router = useRouter();
  const t = useT();
  const [form, setForm] = useState({
    type: "build",
    workspace_id: "default",
    requirement: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.requirement.trim()) {
      setError(t.jobNew.errorEmpty);
      return;
    }
    setLoading(true);
    setError("");

    try {
      const res = await fetch("/api/proxy/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data?.detail || t.jobNew.errorRequest(res.status));
        return;
      }

      const job = await res.json();
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(t.jobNew.errorNetwork);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">{t.jobNew.title}</h1>
        <p className="text-slate-400 text-sm mt-1">{t.jobNew.subtitle}</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Type selector */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-3">{t.jobNew.taskType}</label>
          <div className="grid grid-cols-2 gap-3">
            {(
              [
                { value: "build", icon: "🚀", title: t.jobNew.buildTitle, desc: t.jobNew.buildDesc },
                { value: "update", icon: "🔄", title: t.jobNew.updateTitle, desc: t.jobNew.updateDesc },
              ] as const
            ).map(({ value, icon, title, desc }) => (
              <button
                key={value}
                type="button"
                onClick={() => setForm((f) => ({ ...f, type: value }))}
                className={`p-4 rounded-xl border text-left transition-all ${
                  form.type === value
                    ? "border-blue-500 bg-blue-500/10 text-white"
                    : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500"
                }`}
              >
                <div className="text-2xl mb-2">{icon}</div>
                <div className="font-medium text-sm">{title}</div>
                <div className="text-xs mt-1 opacity-70">{desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Workspace ID */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            {t.jobNew.workspaceId}
          </label>
          <input
            type="text"
            value={form.workspace_id}
            onChange={(e) => setForm((f) => ({ ...f, workspace_id: e.target.value }))}
            placeholder="default"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-200 text-sm focus:outline-none focus:border-blue-500 transition-colors"
          />
          <p className="text-xs text-slate-500 mt-1">
            {t.jobNew.workspaceHint}
          </p>
        </div>

        {/* Requirement */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            {t.jobNew.requirement}
          </label>
          <textarea
            value={form.requirement}
            onChange={(e) => setForm((f) => ({ ...f, requirement: e.target.value }))}
            placeholder={
              form.type === "update"
                ? t.jobNew.placeholderUpdate
                : t.jobNew.placeholderBuild
            }
            rows={5}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-slate-200 text-sm focus:outline-none focus:border-blue-500 transition-colors resize-none"
          />
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-700 text-red-300 text-sm px-4 py-3 rounded-lg">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium py-3 rounded-xl transition-colors flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <span className="animate-spin">⟳</span> {t.jobNew.submitting}
            </>
          ) : (
            <>
              <span>▶</span> {t.jobNew.submit}
            </>
          )}
        </button>
      </form>
    </div>
  );
}
