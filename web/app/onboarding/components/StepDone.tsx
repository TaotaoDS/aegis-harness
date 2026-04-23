interface Props {
  onGo: () => void;
}

const QUICK_START = [
  "前往「💬 对话」页面，用自然语言描述你想构建的内容",
  "CEO Agent 会提问澄清需求，直到置信度 ≥ 95%",
  "系统自动分解任务、编写代码、沙箱验证、QA 审核",
  "在「任务总览」查看所有进度和交付物",
];

export function StepDone({ onGo }: Props) {
  return (
    <div className="text-center space-y-8">
      {/* Success icon */}
      <div className="space-y-4">
        <div className="w-20 h-20 rounded-full bg-green-950/60 border-2 border-green-500 flex items-center justify-center mx-auto text-3xl text-green-400">
          ✓
        </div>
        <h2 className="text-2xl font-bold text-white">配置完成！</h2>
        <p className="text-slate-400 text-sm leading-relaxed">
          AegisHarness 已就绪。你可以随时在「设置」页面修改 API Key 和模型配置。
        </p>
      </div>

      {/* Quick start checklist */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-5 text-left space-y-3">
        <p className="text-xs text-slate-500 uppercase tracking-wider">快速开始</p>
        {QUICK_START.map((tip, i) => (
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
        进入 AegisHarness →
      </button>
    </div>
  );
}
