"use client";

import { useT } from "@/lib/i18n";

interface Props {
  onNext: () => void;
  onSkip: () => void;
}

export function StepWelcome({ onNext, onSkip }: Props) {
  const t = useT();
  const { features, title, subtitle, subtitleLine2, start, skip } =
    t.onboarding.welcome;

  return (
    <div className="space-y-8 text-center">
      {/* Hero */}
      <div className="space-y-3">
        <h1 className="text-3xl font-bold text-white">{title}</h1>
        <p className="text-slate-400 leading-relaxed">
          {subtitle}
          <br />
          {subtitleLine2}
        </p>
      </div>

      {/* Feature pills */}
      <div className="grid grid-cols-3 gap-3">
        {features.map((f) => (
          <div
            key={f.label}
            className="bg-slate-800/60 border border-slate-700 rounded-xl p-4 text-left"
          >
            <div className="text-2xl mb-2">{f.icon}</div>
            <div className="text-sm font-semibold text-white leading-tight">{f.label}</div>
            <div className="text-xs text-slate-400 mt-1 leading-snug">{f.desc}</div>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div className="space-y-3">
        <button
          onClick={onNext}
          className="w-full bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-semibold py-3 px-6 rounded-xl transition-colors text-sm"
        >
          {start}
        </button>
        <button
          onClick={onSkip}
          className="w-full text-slate-500 hover:text-slate-300 text-sm py-2 transition-colors"
        >
          {skip}
        </button>
      </div>
    </div>
  );
}
