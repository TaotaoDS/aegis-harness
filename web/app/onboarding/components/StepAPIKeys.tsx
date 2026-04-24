"use client";

import { useMemo, useState } from "react";
import { useT } from "@/lib/i18n";
import {
  ALL_PROVIDERS,
  PROVIDER_GROUPS,
  isProviderConfigured,
  makeDefaultConfig,
  type ProvidersState,
  type ProviderConfig,
} from "../providers";

interface Props {
  initial: ProvidersState;
  onNext: (providers: ProvidersState) => void;
  onBack: () => void;
}

function buildInitialConfigs(initial: ProvidersState): ProvidersState {
  return Object.fromEntries(
    ALL_PROVIDERS.map((p) => [p.id, makeDefaultConfig(p, initial[p.id])]),
  );
}

export function StepAPIKeys({ initial, onNext, onBack }: Props) {
  const t  = useT();
  const ta = t.onboarding.apiKeys;

  const [selectedId, setSelectedId] = useState(ALL_PROVIDERS[0].id);
  const [configs, setConfigs]       = useState<ProvidersState>(() => buildInitialConfigs(initial));
  const [keyVisible, setKeyVisible] = useState(false);
  const [error, setError]           = useState("");

  const selectedDef = ALL_PROVIDERS.find((p) => p.id === selectedId)!;
  const selectedCfg = configs[selectedId];

  const configuredProviders = useMemo(
    () => ALL_PROVIDERS.filter((p) => isProviderConfigured(p.id, configs)),
    [configs],
  );

  const updateField = (field: keyof ProviderConfig, value: string) => {
    setConfigs((prev) => ({
      ...prev,
      [selectedId]: { ...prev[selectedId], [field]: value },
    }));
    setError("");
  };

  const handleProviderClick = (id: string) => {
    setSelectedId(id);
    setKeyVisible(false);
  };

  const handleNext = () => {
    if (configuredProviders.length === 0) {
      setError(ta.error);
      return;
    }
    const filtered = Object.fromEntries(
      configuredProviders.map((p) => [p.id, configs[p.id]]),
    );
    onNext(filtered);
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
          {ta.step}
        </p>
        <h2 className="text-2xl font-bold text-white">{ta.title}</h2>
        <p className="text-slate-400 text-sm mt-2 leading-relaxed">{ta.subtitle}</p>
      </div>

      <div className="flex border border-slate-700 rounded-xl overflow-hidden h-[400px]">

        {/* Left: provider sidebar */}
        <div className="w-44 flex-shrink-0 border-r border-slate-700 overflow-y-auto bg-slate-900/60">
          {PROVIDER_GROUPS.map((group) => (
            <div key={group.key}>
              {/* Group heading */}
              <p className="px-3 pt-3 pb-1 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                {ta[group.labelKey]}
              </p>

              {ALL_PROVIDERS.filter((p) => p.group === group.key).map((p) => {
                const configured = isProviderConfigured(p.id, configs);
                const active     = p.id === selectedId;
                return (
                  <button
                    key={p.id}
                    onClick={() => handleProviderClick(p.id)}
                    className={[
                      "w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-colors border-l-2",
                      active
                        ? "bg-blue-600/20 text-white border-blue-500"
                        : "text-slate-400 hover:text-white hover:bg-slate-800/60 border-transparent",
                    ].join(" ")}
                  >
                    <span
                      className={[
                        "w-1.5 h-1.5 rounded-full flex-shrink-0",
                        configured ? "bg-green-400" : "bg-slate-700",
                      ].join(" ")}
                    />
                    <span className="truncate leading-snug">{p.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
          {/* Bottom padding so last item isn't cut off */}
          <div className="h-3" />
        </div>

        {/* Right: config form */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 min-w-0">

          {/* Provider header row */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-white leading-tight">
                {selectedDef.label}
              </span>
              {selectedDef.badge && (
                <span
                  className={`text-[10px] border px-1.5 py-0.5 rounded leading-none ${selectedDef.badgeClass}`}
                >
                  {selectedDef.badge}
                </span>
              )}
            </div>
            {selectedDef.docsUrl && (
              <a
                href={selectedDef.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 transition-colors flex-shrink-0"
              >
                {ta.docsHint} →
              </a>
            )}
          </div>

          {/* API Key */}
          {selectedDef.noApiKey ? (
            <p className="text-xs text-slate-500 italic">{ta.noKeyRequired}</p>
          ) : (
            <div>
              <label className="text-xs font-medium text-slate-400 block mb-1">
                {ta.apiKeyLabel}
              </label>
              <div className="relative">
                <input
                  type={keyVisible ? "text" : "password"}
                  className="w-full bg-slate-900 border border-slate-700 focus:border-blue-500 rounded-lg px-3 py-2 text-white text-sm pr-14 outline-none transition-colors placeholder:text-slate-600 font-mono"
                  placeholder={selectedDef.keyPlaceholder || "…"}
                  value={selectedCfg.apiKey}
                  onChange={(e) => updateField("apiKey", e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
                <button
                  type="button"
                  onClick={() => setKeyVisible((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {keyVisible ? ta.hide : ta.show}
                </button>
              </div>
            </div>
          )}

          {/* Base URL */}
          <div>
            <label className="text-xs font-medium text-slate-400 block mb-1">
              {ta.baseUrlLabel}
            </label>
            <input
              type="text"
              className="w-full bg-slate-900 border border-slate-700 focus:border-blue-500 rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors font-mono placeholder:text-slate-600"
              placeholder={selectedDef.defaultBaseUrl || "https://…"}
              value={selectedCfg.baseUrl}
              onChange={(e) => updateField("baseUrl", e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          {/* Model identifier */}
          <div>
            <label className="text-xs font-medium text-slate-400 block mb-1">
              {ta.modelLabel}
            </label>
            <input
              type="text"
              className="w-full bg-slate-900 border border-slate-700 focus:border-blue-500 rounded-lg px-3 py-2 text-white text-sm outline-none transition-colors font-mono placeholder:text-slate-600"
              placeholder={
                selectedDef.suggestedModel
                  ? ta.modelPlaceholder(selectedDef.suggestedModel)
                  : ta.modelLabel
              }
              value={selectedCfg.model}
              onChange={(e) => updateField("model", e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          {/* Configured badge */}
          {isProviderConfigured(selectedId, configs) && (
            <div className="flex items-center gap-1.5 text-xs text-green-400">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 inline-block" />
              {ta.configured}
            </div>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-950/60 border border-red-800 rounded-lg px-4 py-3 text-red-300 text-sm">
          ⚠️ {error}
        </div>
      )}

      {/* Navigation */}
      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 transition-colors"
        >
          {ta.back}
        </button>
        <button
          onClick={handleNext}
          className="flex-1 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-semibold py-2.5 rounded-xl transition-colors text-sm"
        >
          {ta.next}
          {configuredProviders.length > 0 && (
            <span className="ml-1.5 text-blue-200 font-normal">
              ({configuredProviders.length})
            </span>
          )}
        </button>
      </div>
    </div>
  );
}
