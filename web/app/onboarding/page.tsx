"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useT } from "@/lib/i18n";
import { ALL_PROVIDERS, type ProvidersState } from "./providers";
import { StepWelcome }  from "./components/StepWelcome";
import { StepAPIKeys }  from "./components/StepAPIKeys";
import { StepDatabase } from "./components/StepDatabase";
import { StepModel }    from "./components/StepModel";
import { StepDone }     from "./components/StepDone";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OnboardingData {
  providers:    ProvidersState;
  databaseUrl:  string;
  dbConnected:  boolean;
  defaultModel: string;
}

// ---------------------------------------------------------------------------
// Save helper
// ---------------------------------------------------------------------------

async function saveSettings(data: OnboardingData): Promise<void> {
  const calls: Promise<Response>[] = [];

  // ── 1. Extract API keys ────────────────────────────────────────────────
  const apiKeys: Record<string, string> = {};
  for (const [id, cfg] of Object.entries(data.providers)) {
    const def = ALL_PROVIDERS.find((p) => p.id === id);
    if (def?.envKey && cfg.apiKey.trim()) {
      apiKeys[def.envKey] = cfg.apiKey.trim();
    }
  }

  if (Object.keys(apiKeys).length > 0) {
    calls.push(
      fetch("/api/proxy/settings/api_keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: apiKeys }),
      }),
    );
  }

  // ── 2. Database URL ────────────────────────────────────────────────────
  if (data.databaseUrl) {
    calls.push(
      fetch("/api/proxy/settings/database_url", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: data.databaseUrl }),
      }),
    );
  }

  // ── 3. Model config (default model + per-provider base URLs & models) ──
  const providerBaseUrls: Record<string, string> = {};
  const providerModels:   Record<string, string> = {};

  for (const [id, cfg] of Object.entries(data.providers)) {
    const def = ALL_PROVIDERS.find((p) => p.id === id);
    if (!def) continue;
    // Only persist a custom base URL when it differs from the default
    if (cfg.baseUrl.trim() && cfg.baseUrl.trim() !== def.defaultBaseUrl) {
      providerBaseUrls[id] = cfg.baseUrl.trim();
    }
    if (cfg.model.trim()) {
      providerModels[id] = cfg.model.trim();
    }
  }

  calls.push(
    fetch("/api/proxy/settings/model_config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        value: {
          default_model:       data.defaultModel,
          provider_base_urls:  providerBaseUrls,
          provider_models:     providerModels,
        },
      }),
    }),
  );

  // ── 4. Mark onboarding complete ────────────────────────────────────────
  calls.push(
    fetch("/api/proxy/settings/onboarded", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: true }),
    }),
  );

  const results = await Promise.all(calls);
  const failed  = results.find((r) => !r.ok);
  if (failed) throw new Error(`HTTP ${failed.status}`);
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

// steps: 0=Welcome  1=APIKeys  2=Database  3=Model  4=Done
// progress bar covers steps 1-3 (shown when step > 0 && step < TOTAL_STEPS)
const TOTAL_STEPS = 4;

export default function OnboardingPage() {
  const router = useRouter();
  const t      = useT();

  const [step, setStep] = useState(0);
  const [data, setData] = useState<OnboardingData>({
    providers:    {},
    databaseUrl:  "",
    dbConnected:  false,
    defaultModel: "",
  });
  const [saving,    setSaving]    = useState(false);
  const [saveError, setSaveError] = useState("");

  const next = () => setStep((s) => s + 1);
  const back = () => setStep((s) => Math.max(0, s - 1));

  const handleComplete = async (model: string) => {
    const finalData: OnboardingData = { ...data, defaultModel: model };
    setSaving(true);
    setSaveError("");
    try {
      await saveSettings(finalData);
      next(); // → StepDone
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : t.onboarding.model.errorHint,
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {/* Top progress bar (hidden on welcome / done) */}
      {step > 0 && step < TOTAL_STEPS && (
        <div className="fixed top-0 left-0 right-0 z-50 h-0.5 bg-slate-800">
          <div
            className="h-full bg-blue-500 transition-all duration-500 ease-out"
            style={{ width: `${(step / TOTAL_STEPS) * 100}%` }}
          />
        </div>
      )}

      {/* Step content */}
      {step === 0 && (
        <StepWelcome onNext={next} onSkip={() => router.push("/")} />
      )}

      {step === 1 && (
        <StepAPIKeys
          initial={data.providers}
          onNext={(providers) => {
            setData((d) => ({ ...d, providers }));
            next();
          }}
          onBack={back}
        />
      )}

      {step === 2 && (
        <StepDatabase
          initial={data.databaseUrl}
          onNext={(url, connected) => {
            setData((d) => ({ ...d, databaseUrl: url, dbConnected: connected }));
            next();
          }}
          onBack={back}
        />
      )}

      {step === 3 && (
        <StepModel
          providers={data.providers}
          initial={data.defaultModel}
          onComplete={handleComplete}
          onBack={back}
          saving={saving}
          saveError={saveError}
        />
      )}

      {step === 4 && (
        <StepDone dbConnected={data.dbConnected} onGo={() => router.push("/")} />
      )}
    </>
  );
}
