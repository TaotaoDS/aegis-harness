"use client";

import { useState } from "react";

// ---------------------------------------------------------------------------
// Provider definitions
// ---------------------------------------------------------------------------

const PROVIDERS = [
  {
    key: "ANTHROPIC_API_KEY",
    label: "Anthropic (Claude)",
    placeholder: "sk-ant-api03-…",
    badge: "推荐",
    badgeClass: "bg-violet-900/50 text-violet-300 border-violet-700",
    hint: "claude-3-5-sonnet 等，CEO + Architect 首选",
    docsUrl: "https://console.anthropic.com/settings/keys",
  },
  {
    key: "OPENAI_API_KEY",
    label: "OpenAI (GPT-4)",
    placeholder: "sk-…",
    badge: "",
    badgeClass: "",
    hint: "gpt-4o / gpt-4o-mini，与 Anthropic 可并存",
    docsUrl: "https://platform.openai.com/api-keys",
  },
  {
    key: "DEEPSEEK_API_KEY",
    label: "DeepSeek",
    placeholder: "sk-…",
    badge: "高性价比",
    badgeClass: "bg-emerald-900/50 text-emerald-300 border-emerald-700",
    hint: "DeepSeek V3 / R1，中文表现优秀",
    docsUrl: "https://platform.deepseek.com/api_keys",
  },
] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  initial: Record<string, string>;
  onNext: (keys: Record<string, string>) => void;
  onBack: () => void;
}

export function StepAPIKeys({ initial, onNext, onBack }: Props) {
  const [keys, setKeys] = useState<Record<string, string>>(initial);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");

  const hasAny = Object.values(keys).some((v) => v.trim().length > 0);

  const handleNext = () => {
    if (!hasAny) {
      setError("请至少填写一个 API Key 才能继续。");
      return;
    }
    const filtered = Object.fromEntries(
      Object.entries(keys).filter(([, v]) => v.trim().length > 0),
    );
    onNext(filtered);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
          第 1 步 / 共 2 步
        </p>
        <h2 className="text-2xl font-bold text-white">配置 API Key</h2>
        <p className="text-slate-400 text-sm mt-2 leading-relaxed">
          AegisHarness 直接调用 LLM API。Key 仅保存在你本地的数据库中，
          不会上传到任何第三方服务器。
        </p>
      </div>

      {/* Provider fields */}
      <div className="space-y-5">
        {PROVIDERS.map((p) => (
          <div key={p.key}>
            <label className="flex items-center gap-2 text-sm font-medium text-slate-300 mb-1.5">
              {p.label}
              {p.badge && (
                <span
                  className={`text-xs border px-1.5 py-0.5 rounded font-normal ${p.badgeClass}`}
                >
                  {p.badge}
                </span>
              )}
              <a
                href={p.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto text-xs text-slate-600 hover:text-slate-400 transition-colors"
              >
                获取 Key ↗
              </a>
            </label>
            <div className="relative">
              <input
                type={visible[p.key] ? "text" : "password"}
                className="w-full bg-slate-900 border border-slate-700 focus:border-blue-500 rounded-lg px-3 py-2.5 text-white text-sm pr-16 outline-none transition-colors placeholder:text-slate-600"
                placeholder={p.placeholder}
                value={keys[p.key] ?? ""}
                onChange={(e) => {
                  setKeys((k) => ({ ...k, [p.key]: e.target.value }));
                  setError("");
                }}
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500 hover:text-slate-300 transition-colors w-10 text-right"
                onClick={() =>
                  setVisible((v) => ({ ...v, [p.key]: !v[p.key] }))
                }
              >
                {visible[p.key] ? "隐藏" : "显示"}
              </button>
            </div>
            <p className="text-xs text-slate-600 mt-1">{p.hint}</p>
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-950/60 border border-red-800 rounded-lg px-4 py-3 text-red-300 text-sm">
          ⚠️ {error}
        </div>
      )}

      {/* Navigation */}
      <div className="flex gap-3 pt-1">
        <button
          onClick={onBack}
          className="px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 transition-colors"
        >
          ← 返回
        </button>
        <button
          onClick={handleNext}
          className="flex-1 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-semibold py-2.5 rounded-xl transition-colors text-sm"
        >
          下一步 →
        </button>
      </div>
    </div>
  );
}
