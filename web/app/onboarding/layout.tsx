/**
 * Onboarding layout — full-screen, no top nav.
 * Each wizard step renders inside a centred card on the dark background.
 */
export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#0a0f1e] text-slate-200 flex flex-col items-center justify-center p-6">
      {/* Subtle brand mark at the top */}
      <div className="flex items-center gap-2 mb-10 select-none">
        <span className="text-2xl">⚙️</span>
        <span className="font-bold text-white text-lg tracking-tight">AegisHarness</span>
      </div>

      {/* Wizard card */}
      <div className="w-full max-w-lg">{children}</div>

      {/* Version badge */}
      <p className="mt-10 text-xs text-slate-600">v0.0.1</p>
    </div>
  );
}
