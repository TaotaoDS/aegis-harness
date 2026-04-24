"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n";
import { ALL_PROVIDERS, isProviderConfigured, type ProvidersState } from "../providers";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  providers: ProvidersState;
  initial: string;
  onComplete: (model: string) => void;
  onBack: () => void;
  saving: boolean;
  saveError: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StepModel({
  providers,
  initial,
  onComplete,
  onBack,
  saving,
  saveError,
}: Props) {
  const t  = useT();
  const tm = t.onboarding.model;

  // Build the list of usable (configured + has model name) options
  const options = ALL_PROVIDERS
    .filter((p) => isProviderConfigured(p.id, providers) && providers[p.id]?.model)
    .map((p) => ({
      id:          p.id,
      label:       p.label,
      model:       providers[p.id].model,
      recommended: p.badge === "recommended",
      badge:       p.badge,
      badgeClass:  p.badgeClass,
    }));

  const [selected, setSelected] = useState(
    initial || options[0]?.model || "",
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
          {tm.step}
        </p>
        <h2 className="text-2xl font-bold text-white">{tm.title}</h2>
        <p className="text-slate-400 text-sm mt-2">{tm.subtitle}</p>
      </div>

      {/* Option list */}
      {options.length === 0 ? (
        <div className="bg-yellow-950/50 border border-yellow-800 rounded-lg px-4 py-3 text-yellow-300 text-sm">
          {tm.noKeys}
        </div>
      ) : (
        <div className="space-y-2">
          {options.map((opt) => {
            const active = selected === opt.model;
            return (
              <button
                key={opt.id}
                onClick={() => setSelected(opt.model)}
                className={[
                  "w-full text-left px-4 py-3 rounded-xl border transition-all",
                  active
                    ? "border-blue-500 bg-blue-950/40 ring-1 ring-blue-500/60"
                    : "border-slate-700 bg-slate-800/50 hover:border-slate-500",
                ].join(" ")}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs text-slate-500 truncate">{opt.label}</p>
                    <p className="text-sm font-mono font-semibold text-white truncate mt-0.5">
                      {opt.model}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {opt.recommended && (
                      <span className="text-xs bg-blue-900/60 text-blue-300 border border-blue-700 px-1.5 py-0.5 rounded">
                        {tm.recommended}
                      </span>
                    )}
                    {active && <span className="text-blue-400 text-sm">✓</span>}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Save error */}
      {saveError && (
        <div className="bg-red-950/60 border border-red-800 rounded-lg px-4 py-3 space-y-1">
          <p className="text-red-300 text-sm font-medium">⚠️ {saveError}</p>
          <p className="text-red-400/80 text-xs">{tm.errorHint}</p>
        </div>
      )}

      {/* Navigation */}
      <div className="flex gap-3 pt-1">
        <button
          onClick={onBack}
          disabled={saving}
          className="px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 transition-colors disabled:opacity-40"
        >
          {tm.back}
        </button>
        <button
          onClick={() => onComplete(selected)}
          disabled={saving || !selected || options.length === 0}
          className="flex-1 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:opacity-40 text-white font-semibold py-2.5 rounded-xl transition-colors text-sm"
        >
          {saving ? tm.saving : tm.complete}
        </button>
      </div>
    </div>
  );
}
