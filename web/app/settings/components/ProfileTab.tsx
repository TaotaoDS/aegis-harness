"use client";

import { useState } from "react";

export interface UserProfile {
  name: string;
  role: string;
  technical_level: "technical" | "semi_technical" | "non_technical";
  language: string;
  notes: string;
}

const TECH_LEVELS = [
  {
    value: "technical",
    label: "技术型",
    badge: "bg-blue-900/50 text-blue-300 border-blue-700",
    desc: "工程师 / 开发者，全量技术词汇",
  },
  {
    value: "semi_technical",
    label: "半技术型",
    badge: "bg-yellow-900/50 text-yellow-300 border-yellow-700",
    desc: "产品 / 设计 / 分析师，轻技术术语",
  },
  {
    value: "non_technical",
    label: "非技术型",
    badge: "bg-purple-900/50 text-purple-300 border-purple-700",
    desc: "业务方 / 创业者，纯大白话 + 选项引导",
  },
];

interface Props {
  initial: UserProfile;
  onSave: (profile: UserProfile) => Promise<void>;
}

export function ProfileTab({ initial, onSave }: Props) {
  const [form, setForm] = useState<UserProfile>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const update = (key: keyof UserProfile, val: string) => {
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
        <h2 className="text-lg font-semibold text-white mb-1">用户背景画像</h2>
        <p className="text-slate-400 text-sm">
          CEO Agent 将在每次任务开始时读取此配置，自动调整沟通策略。
        </p>
      </div>

      {/* Name + Role */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">
            姓名
          </label>
          <input
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
            placeholder="你的名字"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">
            职位 / 角色
          </label>
          <input
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
            value={form.role}
            onChange={(e) => update("role", e.target.value)}
            placeholder="e.g. Product Manager, CTO, 创始人"
          />
        </div>
      </div>

      {/* Technical level */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          技术水平
        </label>
        <div className="grid grid-cols-3 gap-3">
          {TECH_LEVELS.map((lvl) => (
            <button
              key={lvl.value}
              onClick={() => update("technical_level", lvl.value)}
              className={`rounded-xl border p-4 text-left transition-all ${
                form.technical_level === lvl.value
                  ? "border-blue-500 bg-blue-900/30 ring-1 ring-blue-500"
                  : "border-slate-700 bg-slate-800/50 hover:border-slate-500"
              }`}
            >
              <span
                className={`inline-block text-xs font-semibold px-2 py-0.5 rounded border ${lvl.badge} mb-2`}
              >
                {lvl.label}
              </span>
              <p className="text-xs text-slate-400 leading-snug">{lvl.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Language */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">
          首选语言
        </label>
        <select
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
          value={form.language}
          onChange={(e) => update("language", e.target.value)}
        >
          <option value="auto">自动检测（推荐）</option>
          <option value="zh">中文</option>
          <option value="en">English</option>
          <option value="ja">日本語</option>
          <option value="ko">한국어</option>
        </select>
        <p className="text-xs text-slate-500 mt-1">
          "自动检测"让 CEO 根据你的需求描述自动识别并使用相同语言回复。
        </p>
      </div>

      {/* Notes */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">
          背景备注（可选）
        </label>
        <textarea
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500 resize-none"
          rows={3}
          value={form.notes}
          onChange={(e) => update("notes", e.target.value)}
          placeholder="任何对 CEO 有帮助的背景信息，例如：我们是一个 B2B SaaS 公司，主要客户是中小型制造企业…"
        />
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
        {saving ? "保存中…" : saved ? "✓ 已保存" : "保存画像"}
      </button>
    </div>
  );
}
