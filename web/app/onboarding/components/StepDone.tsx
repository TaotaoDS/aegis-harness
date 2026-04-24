"use client";

import { useT } from "@/lib/i18n";

interface Props {
  onGo: () => void;
  dbConnected?: boolean;
}

export function StepDone({ onGo, dbConnected }: Props) {
  const t = useT();
  const td = t.onboarding.done;

  return (
    <div className="text-center space-y-8">
      {/* Success icon */}
      <div className="space-y-4">
        <div className="w-20 h-20 rounded-full bg-green-950/60 border-2 border-green-500 flex items-center justify-center mx-auto text-3xl text-green-400">
          ✓
        </div>
        <h2 className="text-2xl font-bold text-white">{td.title}</h2>
        <p className="text-slate-400 text-sm leading-relaxed">{td.subtitle}</p>
      </div>

      {/* DB mode indicator */}
      <div
        className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-sm ${
          dbConnected
            ? "bg-green-950/40 border-green-800 text-green-300"
            : "bg-amber-950/40 border-amber-800 text-amber-300"
        }`}
      >
        <span className="text-base">{dbConnected ? "🟢" : "🟡"}</span>
        <div className="text-left">
          <p className="font-medium">
            {dbConnected ? td.dbConnected : td.dbFile}
          </p>
          <p className="text-xs opacity-70 mt-0.5">
            {dbConnected ? td.dbConnectedDesc : td.dbFileDesc}
          </p>
        </div>
      </div>

      {/* Quick start checklist */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-5 text-left space-y-3">
        <p className="text-xs text-slate-500 uppercase tracking-wider">{td.quickStart}</p>
        {td.tips.map((tip, i) => (
          <div key={i} className="flex items-start gap-3 text-sm text-slate-300">
            <span className="w-5 h-5 rounded-full bg-blue-950/60 border border-blue-700/60 text-blue-300 text-xs flex items-center justify-center flex-shrink-0 mt-0.5 font-medium">
              {i + 1}
            </span>
            <span>{tip}</span>
          </div>
        ))}
      </div>

      <button
        onClick={onGo}
        className="w-full bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-semibold py-3 rounded-xl transition-colors"
      >
        {td.goBtn}
      </button>
    </div>
  );
}
