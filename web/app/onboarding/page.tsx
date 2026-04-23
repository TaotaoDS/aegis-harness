"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { StepWelcome } from "./components/StepWelcome";
import { StepAPIKeys } from "./components/StepAPIKeys";
import { StepModel } from "./components/StepModel";
import { StepDone } from "./components/StepDone";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OnboardingData {
  apiKeys: Record<string, string>;
  defaultModel: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function saveSettings(data: OnboardingData): Promise<void> {
  const calls: Promise<Response>[] = [];

  if (Object.keys(data.apiKeys).length > 0) {
    calls.push(
      fetch("/api/proxy/settings/api_keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: data.apiKeys }),
      }),
    );
  }

  if (data.defaultModel) {
    calls.push(
      fetch("/api/proxy/settings/model_config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: { default_model: data.defaultModel } }),
      }),
    );
  }

  // Mark onboarding complete so the dashboard won't redirect again
  calls.push(
    fetch("/api/proxy/settings/onboarded", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value: true }),
    }),
  );

  const results = await Promise.all(calls);
  const failed = results.find((r) => !r.ok);
  if (failed) throw new Error(`HTTP ${failed.status}`);
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const TOTAL_STEPS = 3; // steps 1-3 out of 0-3 (welcome is 0, done is 3)

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [data, setData] = useState<OnboardingData>({ apiKeys: {}, defaultModel: "" });
  const [saving, setSaving] = useState(false);
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
        err instanceof Error ? err.message : "保存失败，请检查后端服务是否正在运行。",
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
          initial={data.apiKeys}
          onNext={(keys) => {
            setData((d) => ({ ...d, apiKeys: keys }));
            next();
          }}
          onBack={back}
        />
      )}

      {step === 2 && (
        <StepModel
          apiKeys={data.apiKeys}
          initial={data.defaultModel}
          onComplete={handleComplete}
          onBack={back}
          saving={saving}
          saveError={saveError}
        />
      )}

      {step === 3 && <StepDone onGo={() => router.push("/")} />}
    </>
  );
}
