"use client";

interface Props {
  passed: boolean;
  data: Record<string, unknown>;
}

/**
 * Pass/fail verdict card for evaluator and QA events.
 *
 * Rendered for: evaluator.pass, evaluator.fail, qa.pass, qa.fail
 */
export function QAVerdict({ passed, data }: Props) {
  const feedback = (data.feedback as string) ?? "";
  const issues   = (data.issues   as string[]) ?? [];

  return (
    <div
      className={`rounded-xl border px-4 py-3 ${
        passed
          ? "border-green-700/50 bg-green-900/10"
          : "border-red-700/50 bg-red-900/10"
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{passed ? "✅" : "❌"}</span>
        <span
          className={`text-sm font-semibold ${
            passed ? "text-green-300" : "text-red-300"
          }`}
        >
          {passed ? "验证通过" : "验证未通过"}
        </span>
      </div>

      {feedback && (
        <p className="text-slate-300 text-xs leading-relaxed">{feedback}</p>
      )}

      {!passed && issues.length > 0 && (
        <ul className="mt-2 space-y-1">
          {issues.map((issue, idx) => (
            <li key={idx} className="text-red-300 text-xs flex gap-2">
              <span className="text-red-500 shrink-0">•</span>
              {issue}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
