interface Props {
  onNext: () => void;
  onSkip: () => void;
}

const FEATURES = [
  { icon: "🤖", label: "CEO 访谈", desc: "95% 置信度需求澄清，不再猜测" },
  { icon: "⚡", label: "波次并行", desc: "Kahn BFS 调度，多任务并发执行" },
  { icon: "🧠", label: "语义记忆", desc: "pgvector 经验库，越用越聪明" },
];

export function StepWelcome({ onNext, onSkip }: Props) {
  return (
    <div className="space-y-8 text-center">
      {/* Hero */}
      <div className="space-y-3">
        <h1 className="text-3xl font-bold text-white">欢迎使用 AegisHarness</h1>
        <p className="text-slate-400 leading-relaxed">
          多智能体代码生成平台。描述你的需求，AI 自动完成
          <br />
          需求访谈 → 任务分解 → 代码编写 → 质量验证。
        </p>
      </div>

      {/* Feature pills */}
      <div className="grid grid-cols-3 gap-3">
        {FEATURES.map((f) => (
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
          开始配置  →
        </button>
        <button
          onClick={onSkip}
          className="w-full text-slate-500 hover:text-slate-300 text-sm py-2 transition-colors"
        >
          跳过，我已配置过
        </button>
      </div>
    </div>
  );
}
