"use client";

import { useState } from "react";

interface APIKeys {
  anthropic?: string;
  openai?: string;
  nvidia?: string;
  deepseek?: string;
  zhipu?: string;
  moonshot?: string;
}

interface Props {
  initial: APIKeys;
  onSave: (keys: APIKeys) => Promise<void>;
}

const PROVIDERS = [
  {
    key: "anthropic" as keyof APIKeys,
    name: "Anthropic (Claude)",
    placeholder: "sk-ant-api03-…",
    link: "https://console.anthropic.com",
    badge: "text-orange-300 bg-orange-900/30 border-orange-700",
  },
  {
    key: "openai" as keyof APIKeys,
    name: "OpenAI (GPT)",
    placeholder: "sk-proj-…",
    link: "https://platform.openai.com/api-keys",
    badge: "text-green-300 bg-green-900/30 border-green-700",
  },
  {
    key: "nvidia" as keyof APIKeys,
    name: "NVIDIA NIM",
    placeholder: "nvapi-…",
    link: "https://build.nvidia.com",
    badge: "text-emerald-300 bg-emerald-900/30 border-emerald-700",
  },
  {
    key: "deepseek" as keyof APIKeys,
    name: "DeepSeek",
    placeholder: "sk-…",
    link: "https://platform.deepseek.com",
    badge: "text-sky-300 bg-sky-900/30 border-sky-700",
  },
  {
    key: "zhipu" as keyof APIKeys,
    name: "智谱 GLM",
    placeholder: "xxxxx.xxxxxxx",
    link: "https://open.bigmodel.cn",
    badge: "text-purple-300 bg-purple-900/30 border-purple-700",
  },
  {
    key: "moonshot" as keyof APIKeys,
    name: "Moonshot / Kimi",
    placeholder: "sk-…",
    link: "https://platform.moonshot.cn",
    badge: "text-cyan-300 bg-cyan-900/30 border-cyan-700",
  },
];

function isMasked(val?: string): boolean {
  return !!(val && val.startsWith("****"));
}

export function APIKeysTab({ initial, onSave }: Props) {
  // Each key starts as "" (user hasn't typed) so we don't accidentally
  // overwrite the masked placeholder that came from the server.
  const [form, setForm] = useState<APIKeys>({});
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const update = (key: keyof APIKeys, val: string) => {
    setForm((f) => ({ ...f, [key]: val }));
    setSaved(false);
  };

  const toggle = (key: string) =>
    setShowKey((s) => ({ ...s, [key]: !s[key] }));

  const handleSave = async () => {
    // Only send keys that the user has actually typed (non-empty, non-masked)
    const toSave: APIKeys = {};
    for (const [k, v] of Object.entries(form)) {
      if (v && !isMasked(v)) {
        (toSave as Record<string, string>)[k] = v;
      }
    }
    if (Object.keys(toSave).length === 0) {
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      return;
    }
    setSaving(true);
    try {
      await onSave(toSave);
      setForm({});   // clear inputs after successful save
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">API Key 管理</h2>
        <p className="text-slate-400 text-sm">
          Key 仅存储在服务端，页面仅展示末四位脱敏内容。更新后无需重启服务。
        </p>
      </div>

      <div className="space-y-3">
        {PROVIDERS.map((p) => {
          const serverVal = (initial as Record<string, string | undefined>)[p.key];
          const formVal = (form as Record<string, string | undefined>)[p.key] ?? "";
          const isSet = !!serverVal;
          const isVisible = showKey[p.key];

          return (
            <div
              key={p.key}
              className="bg-slate-800/50 border border-slate-700 rounded-xl p-4 flex items-center gap-4"
            >
              <div className="w-40 shrink-0">
                <span
                  className={`text-xs font-semibold px-2 py-0.5 rounded border ${p.badge}`}
                >
                  {p.name}
                </span>
                {isSet && (
                  <div className="text-xs text-green-400 mt-1">✓ 已配置</div>
                )}
              </div>

              <div className="flex-1 relative">
                <input
                  type={isVisible ? "text" : "password"}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm font-mono focus:outline-none focus:border-blue-500 pr-10"
                  value={formVal}
                  onChange={(e) => update(p.key, e.target.value)}
                  placeholder={
                    isSet ? serverVal /* shows masked value */ : p.placeholder
                  }
                />
                <button
                  type="button"
                  onClick={() => toggle(p.key)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs"
                >
                  {isVisible ? "隐藏" : "显示"}
                </button>
              </div>

              <a
                href={p.link}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 shrink-0"
              >
                申请 →
              </a>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={saving}
          className={`px-5 py-2 rounded-lg text-sm font-medium transition-colors ${
            saved
              ? "bg-green-600 text-white"
              : "bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
          }`}
        >
          {saving ? "保存中…" : saved ? "✓ 已保存" : "更新 Key"}
        </button>
        <p className="text-xs text-slate-500">
          仅填写需要更新的字段，空白字段将保留原值。
        </p>
      </div>
    </div>
  );
}
