"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function NewJobPage() {
  const router = useRouter();
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
      setError("请输入需求描述");
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
        setError(data?.detail || `请求失败 (${res.status})`);
        return;
      }

      const job = await res.json();
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError("网络错误，请检查后端服务是否启动（port 8000）");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">新建任务</h1>
        <p className="text-slate-400 text-sm mt-1">描述你的需求，Agent 团队将自动完成开发</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Type selector */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-3">任务类型</label>
          <div className="grid grid-cols-2 gap-3">
            {(
              [
                { value: "build", icon: "🚀", title: "全新构建", desc: "从零开始构建新项目" },
                { value: "update", icon: "🔄", title: "迭代更新", desc: "在现有项目基础上修改" },
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
            工作区 ID
          </label>
          <input
            type="text"
            value={form.workspace_id}
            onChange={(e) => setForm((f) => ({ ...f, workspace_id: e.target.value }))}
            placeholder="default"
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-200 text-sm focus:outline-none focus:border-blue-500 transition-colors"
          />
          <p className="text-xs text-slate-500 mt-1">
            相同 workspace_id 可让 Update Mode 操作同一套代码文件
          </p>
        </div>

        {/* Requirement */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            需求描述
          </label>
          <textarea
            value={form.requirement}
            onChange={(e) => setForm((f) => ({ ...f, requirement: e.target.value }))}
            placeholder={
              form.type === "update"
                ? "例如：将登录按钮颜色改为蓝色，并修复表单提交时的 XSS 漏洞"
                : "例如：构建一个带用户认证的 REST API，使用 FastAPI + PostgreSQL"
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
              <span className="animate-spin">⟳</span> 提交中…
            </>
          ) : (
            <>
              <span>▶</span> 启动任务
            </>
          )}
        </button>
      </form>
    </div>
  );
}
