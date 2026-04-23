"use client";

import { useState } from "react";

// ---------------------------------------------------------------------------
// Model catalogue (keyed by provider API key name)
// ---------------------------------------------------------------------------

const PROVIDER_MODELS: {
  providerKey: string;
  providerLabel: string;
  models: { id: string; label: string; desc: string; recommended?: boolean }[];
}[] = [
  {
    providerKey: "ANTHROPIC_API_KEY",
    providerLabel: "Anthropic",
    models: [
      {
        id: "claude-3-5-sonnet-20241022",
        label: "Claude 3.5 Sonnet",
        desc: "性能与成本最佳平衡，推荐用于生产",
        recommended: true,
      },
      {
        id: "claude-3-5-haiku-20241022",
        label: "Claude 3.5 Haiku",
        desc: "更快更经济，适合高频轻量任务",
      },
    ],
  },
  {
    providerKey: "OPENAI_API_KEY",
    providerLabel: "OpenAI",
    models: [
      {
        id: "gpt-4o",
        label: "GPT-4o",
        desc: "OpenAI 旗舰模型，多模态支持",
        recommended: true,
      },
      {
        id: "gpt-4o-mini",
        label: "GPT-4o mini",
        desc: "经济高效，适合 QA / 轻量 Architect",
      },
    ],
  },
  {
    providerKey: "DEEPSEEK_API_KEY",
    providerLabel: "DeepSeek",
    models: [
      {
        id: "deepseek-chat",
        label: "DeepSeek V3",
        desc: "高性价比，中文与代码表现优秀",
        recommended: true,
      },
      {
        id: "deepseek-reasoner",
        label: "DeepSeek R1",
        desc: "推理增强，适合复杂架构决策",
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  apiKeys: Record<string, string>;
  initial: string;
  onComplete: (model: string) => void;
  onBack: () => void;
  saving: boolean;
  saveError: string;
}

export function StepModel({
  apiKeys,
  initial,
  onComplete,
  onBack,
  saving,
  saveError,
}: Props) {
  // Only show provider sections where the user filled in a key
  const available = PROVIDER_MODELS.filter((p) =>
    Object.prototype.hasOwnProperty.call(apiKeys, p.providerKey),
  );
  const allModels = available.flatMap((p) => p.models);
  const [selected, setSelected] = useState(
    initial || allModels.find((m) => m.recommended)?.id || allModels[0]?.id || "",
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
          第 2 步 / 共 2 步
        </p>
        <h2 className="text-2xl font-bold text-white">选择默认模型</h2>
        <p className="text-slate-400 text-sm mt-2">
          CEO Agent 和 Architect Agent 将默认使用此模型。可随时在「设置 → 模型」中调整。
        </p>
      </div>

      {/* Model list */}
      {available.length === 0 ? (
        <div className="bg-yellow-950/50 border border-yellow-800 rounded-lg px-4 py-3 text-yellow-300 text-sm">
          未检测到有效 API Key，请返回上一步填写至少一个。
        </div>
      ) : (
        <div className="space-y-5">
          {available.map((p) => (
            <div key={p.providerKey}>
              <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">
                {p.providerLabel}
              </p>
              <div className="space-y-2">
                {p.models.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setSelected(m.id)}
                    className={`w-full text-left px-4 py-3 rounded-xl border transition-all ${
                      selected === m.id
                        ? "border-blue-500 bg-blue-950/40 ring-1 ring-blue-500/60"
                        : "border-slate-700 bg-slate-800/50 hover:border-slate-500"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white">
                        {m.label}
                      </span>
                      {m.recommended && (
                        <span className="text-xs bg-blue-900/60 text-blue-300 border border-blue-700 px-1.5 py-0.5 rounded">
                          推荐
                        </span>
                      )}
                      {selected === m.id && (
                        <span className="ml-auto text-blue-400 text-sm">✓</span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">{m.desc}</p>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Save error with actionable hint */}
      {saveError && (
        <div className="bg-red-950/60 border border-red-800 rounded-lg px-4 py-3 space-y-1">
          <p className="text-red-300 text-sm font-medium">⚠️ {saveError}</p>
          <p className="text-red-400/80 text-xs">
            请确认 AegisHarness 后端正在运行（端口 8000），
            检查网络连接，然后点击「完成配置」重试。
          </p>
        </div>
      )}

      {/* Navigation */}
      <div className="flex gap-3 pt-1">
        <button
          onClick={onBack}
          disabled={saving}
          className="px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 transition-colors disabled:opacity-40"
        >
          ← 返回
        </button>
        <button
          onClick={() => onComplete(selected)}
          disabled={saving || !selected || available.length === 0}
          className="flex-1 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:opacity-40 text-white font-semibold py-2.5 rounded-xl transition-colors text-sm"
        >
          {saving ? "保存中…" : "完成配置 →"}
        </button>
      </div>
    </div>
  );
}
