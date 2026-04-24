"use client";

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n";

interface ModelEntry {
  provider: string;
  model_id: string;
  tier?: string;
  max_tokens?: number;
  temperature?: number;
}

interface ModelConfig {
  default_model?: string;
}

interface Props {
  initialConfig: ModelConfig;
  onSaveConfig: (config: ModelConfig) => Promise<void>;
}

const TIER_COLORS: Record<string, string> = {
  standard: "text-blue-300 bg-blue-900/30 border-blue-700",
  advanced:  "text-purple-300 bg-purple-900/30 border-purple-700",
};

const PROVIDER_ICONS: Record<string, string> = {
  anthropic: "🟠",
  openai:    "🟢",
};

export function ModelsTab({ initialConfig, onSaveConfig }: Props) {
  const t = useT();
  const [models, setModels] = useState<Record<string, ModelEntry>>({});
  const [defaultModel, setDefaultModel] = useState(initialConfig.default_model ?? "");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Load available models from the backend
  useEffect(() => {
    fetch("/api/proxy/settings/model_runtime")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.value?.models) setModels(d.value.models);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSaveConfig({ default_model: defaultModel });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      // Invalidate model router cache via backend
      await fetch("/api/proxy/settings/model_config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: { default_model: defaultModel } }),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">{t.models.title}</h2>
        <p className="text-slate-400 text-sm">
          {t.models.subtitle}
        </p>
      </div>

      {/* Default model selector */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4">
        <label className="block text-sm font-medium text-slate-300 mb-2">
          {t.models.defaultRoute}
        </label>
        {loading ? (
          <div className="text-slate-500 text-sm">{t.models.loadingModels}</div>
        ) : (
          <div className="flex items-center gap-3">
            <select
              className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
              value={defaultModel}
              onChange={(e) => { setDefaultModel(e.target.value); setSaved(false); }}
            >
              <option value="">{t.models.defaultOption}</option>
              {Object.entries(models).map(([name]) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
            <button
              onClick={handleSave}
              disabled={saving}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors shrink-0 ${
                saved
                  ? "bg-green-600 text-white"
                  : "bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
              }`}
            >
              {saving ? "…" : saved ? "✓" : t.models.apply}
            </button>
          </div>
        )}
        <p className="text-xs text-slate-500 mt-2">
          {t.models.overrideHint}
        </p>
      </div>

      {/* Model list */}
      {loading ? (
        <div className="text-slate-500 text-sm text-center py-8">{t.models.loading}</div>
      ) : Object.keys(models).length === 0 ? (
        <div className="text-center py-8 text-slate-500">
          <p className="text-sm">{t.models.empty}</p>
          <p className="text-xs mt-1">{t.models.emptyHint}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {Object.entries(models).map(([name, m]) => (
            <div
              key={name}
              className={`bg-slate-800/50 border rounded-xl p-4 flex items-center gap-4 transition-all ${
                name === defaultModel
                  ? "border-blue-500/50 ring-1 ring-blue-500/30"
                  : "border-slate-700"
              }`}
            >
              <span className="text-xl w-6 text-center shrink-0">
                {PROVIDER_ICONS[m.provider] ?? "🔵"}
              </span>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-white font-medium">{name}</span>
                  {m.tier && (
                    <span className={`text-xs px-1.5 py-0.5 rounded border ${TIER_COLORS[m.tier] ?? "text-slate-300 bg-slate-700 border-slate-600"}`}>
                      {m.tier}
                    </span>
                  )}
                  {name === defaultModel && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-blue-600 text-white font-medium">
                      {t.models.default}
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {m.provider} · {m.model_id}
                  {m.max_tokens && ` · max_tokens: ${m.max_tokens.toLocaleString()}`}
                  {m.temperature !== undefined && ` · temp: ${m.temperature}`}
                </div>
              </div>

              <button
                onClick={() => { setDefaultModel(name); setSaved(false); }}
                className="text-xs text-slate-500 hover:text-blue-400 transition-colors shrink-0"
              >
                {t.models.setDefault}
              </button>
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-slate-600">
        {t.models.editHint}
      </p>
    </div>
  );
}
