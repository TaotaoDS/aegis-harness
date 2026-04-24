"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n";

type TestStatus = "idle" | "testing" | "success" | "error";

interface Props {
  initial: string;
  onNext: (url: string, connected: boolean) => void;
  onBack: () => void;
}

export function StepDatabase({ initial, onNext, onBack }: Props) {
  const t = useT();
  const td = t.onboarding.database;

  const [url, setUrl] = useState(initial);
  const [status, setStatus] = useState<TestStatus>("idle");
  const [latency, setLatency] = useState<number | null>(null);
  const [errMsg, setErrMsg] = useState("");
  const [showSkipWarning, setShowSkipWarning] = useState(false);

  const handleTest = async () => {
    if (!url.trim()) return;
    setStatus("testing");
    setErrMsg("");
    setShowSkipWarning(false);
    setLatency(null);
    try {
      const res = await fetch("/api/proxy/settings/test_db_connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });
      const data = await res.json();
      if (data.ok) {
        setStatus("success");
        setLatency(data.latency_ms);
      } else {
        setStatus("error");
        setErrMsg(data.error || td.failTitle);
      }
    } catch {
      setStatus("error");
      setErrMsg(td.backendError);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">
          {td.step}
        </p>
        <h2 className="text-2xl font-bold text-white">{td.title}</h2>
        <p className="text-slate-400 text-sm mt-2 leading-relaxed">{td.subtitle}</p>
      </div>

      {/* URL input */}
      <div>
        <label className="text-sm font-medium text-slate-300 mb-1.5 block">
          {td.urlLabel}
        </label>
        <input
          type="text"
          className="w-full bg-slate-900 border border-slate-700 focus:border-blue-500 rounded-lg px-3 py-2.5 text-white text-sm font-mono outline-none transition-colors placeholder:text-slate-600"
          placeholder={td.urlPlaceholder}
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setStatus("idle");
            setErrMsg("");
            setShowSkipWarning(false);
          }}
          spellCheck={false}
          autoComplete="off"
        />
        <p className="text-xs text-slate-600 mt-1">{td.urlHint}</p>
      </div>

      {/* Test result */}
      {status === "success" && (
        <div className="bg-green-950/50 border border-green-800 rounded-lg px-4 py-3 flex items-center gap-3">
          <span className="text-green-400 text-xl leading-none">✓</span>
          <div>
            <p className="text-green-300 text-sm font-medium">{td.successTitle}</p>
            <p className="text-green-500/80 text-xs">
              {latency !== null ? td.successLatency(latency) : ""}
            </p>
          </div>
        </div>
      )}

      {status === "error" && (
        <div className="bg-red-950/60 border border-red-800 rounded-lg px-4 py-3 space-y-1">
          <p className="text-red-300 text-sm font-medium">{td.failTitle}</p>
          <p className="text-red-400/80 text-xs font-mono break-all">{errMsg}</p>
        </div>
      )}

      {/* Skip warning */}
      {showSkipWarning && (
        <div className="bg-amber-950/60 border border-amber-700 rounded-xl px-4 py-4 space-y-3">
          <p className="text-amber-300 text-sm font-semibold">{td.warningTitle}</p>
          <p className="text-amber-200/90 text-sm leading-relaxed">{td.warningText}</p>
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => setShowSkipWarning(false)}
              className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white border border-slate-700 hover:border-slate-500 transition-colors"
            >
              {td.cancelSkip}
            </button>
            <button
              onClick={() => onNext("", false)}
              className="px-4 py-2 rounded-lg text-sm bg-amber-800/60 hover:bg-amber-700/60 text-amber-200 border border-amber-700 transition-colors"
            >
              {td.confirmSkip}
            </button>
          </div>
        </div>
      )}

      {/* Navigation */}
      {!showSkipWarning && (
        <div className="flex gap-3 pt-1">
          <button
            onClick={onBack}
            className="px-4 py-2.5 rounded-xl text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-500 transition-colors"
          >
            {td.back}
          </button>
          <button
            onClick={handleTest}
            disabled={!url.trim() || status === "testing"}
            className="px-4 py-2.5 rounded-xl text-sm text-blue-300 border border-blue-700/60 hover:border-blue-500 disabled:opacity-40 transition-colors"
          >
            {status === "testing" ? td.testing : td.testBtn}
          </button>
          <button
            onClick={
              status === "success"
                ? () => onNext(url.trim(), true)
                : () => setShowSkipWarning(true)
            }
            className={`flex-1 font-semibold py-2.5 rounded-xl transition-colors text-sm ${
              status === "success"
                ? "bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white"
                : "bg-slate-700/80 hover:bg-slate-600/80 text-slate-300 border border-slate-600"
            }`}
          >
            {status === "success" ? td.nextBtn : td.skipBtn}
          </button>
        </div>
      )}
    </div>
  );
}
