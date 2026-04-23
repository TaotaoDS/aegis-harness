"use client";

import { useState } from "react";

interface CEOConfig {
  agent_name: string;
  system_prompt_prefix: string;
}

interface Props {
  initial: CEOConfig;
  onSave: (config: CEOConfig) => Promise<void>;
}

export function CEOTab({ initial, onSave }: Props) {
  const [form, setForm] = useState<CEOConfig>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const update = (key: keyof CEOConfig, val: string) => {
    setForm((f) => ({ ...f, [key]: val }));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(form);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">CEO Agent 配置</h2>
        <p className="text-slate-400 text-sm">
          自定义负责需求访谈与任务分解的首席 Agent 的名称和人设前缀。
        </p>
      </div>

      {/* Agent name */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">
          Agent 称呼
        </label>
        <input
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
          value={form.agent_name}
          onChange={(e) => update("agent_name", e.target.value)}
          placeholder="e.g. CEO、产品顾问、需求分析师"
          maxLength={40}
        />
        <p className="text-xs text-slate-500 mt-1">
          此名称在 Web 界面的对话气泡中展示。
        </p>
      </div>

      {/* System prompt prefix */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">
          系统提示词前缀（可选）
        </label>
        <textarea
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500 resize-none font-mono"
          rows={5}
          value={form.system_prompt_prefix}
          onChange={(e) => update("system_prompt_prefix", e.target.value)}
          placeholder="填写后此内容将被插入到每次访谈的系统提示词头部，例如：&#10;You are working for Acme Corp, a logistics software company.&#10;Always ensure solutions are GDPR-compliant."
        />
        <p className="text-xs text-slate-500 mt-1">
          可用于注入公司背景、行业约束、合规要求等上下文。留空则使用默认提示词。
        </p>
      </div>

      {/* Preview box */}
      <div className="bg-slate-900/50 border border-slate-700 rounded-xl p-4">
        <div className="text-xs text-slate-500 mb-2 uppercase tracking-wide">预览效果</div>
        <div className="flex items-start gap-3">
          <div className="shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-xs font-bold text-white">
            {(form.agent_name || "CEO")[0].toUpperCase()}
          </div>
          <div className="bg-slate-800 rounded-xl rounded-tl-none px-4 py-3 max-w-xs">
            <div className="text-xs text-blue-400 font-medium mb-1">
              {form.agent_name || "CEO Agent"}
            </div>
            <p className="text-slate-300 text-sm">
              你好！我是 {form.agent_name || "CEO Agent"}，将协助你把想法转化为可执行的开发计划。请先告诉我你想构建什么？
            </p>
          </div>
        </div>
      </div>

      <button
        onClick={handleSave}
        disabled={saving}
        className={`px-5 py-2 rounded-lg text-sm font-medium transition-colors ${
          saved
            ? "bg-green-600 text-white"
            : "bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
        }`}
      >
        {saving ? "保存中…" : saved ? "✓ 已保存" : "保存配置"}
      </button>
    </div>
  );
}
