"use client";

import { useState } from "react";

interface Props {
  data: Record<string, unknown>;
}

/** Language → display name mapping for the badge. */
const LANG_LABELS: Record<string, string> = {
  py:   "Python",
  ts:   "TypeScript",
  tsx:  "TSX",
  js:   "JavaScript",
  jsx:  "JSX",
  json: "JSON",
  yaml: "YAML",
  yml:  "YAML",
  md:   "Markdown",
  sh:   "Shell",
  css:  "CSS",
  html: "HTML",
  sql:  "SQL",
  txt:  "Text",
};

function langFromPath(filepath: string): string {
  const ext = filepath.split(".").pop()?.toLowerCase() ?? "";
  return LANG_LABELS[ext] ?? ext.toUpperCase();
}

/**
 * Compact card for a written file — shown when `architect.file_written` fires.
 * Supports expanding to preview the first ~30 lines of content.
 */
export function FileCard({ data }: Props) {
  const filepath = (data.filepath as string) ?? "unknown";
  const content  = (data.content  as string) ?? "";
  const lang     = langFromPath(filepath);

  const [expanded, setExpanded] = useState(false);
  const preview = content.split("\n").slice(0, 30).join("\n");
  const hasMore = content.split("\n").length > 30;

  return (
    <div className="border border-slate-700 rounded-xl overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center justify-between bg-slate-800/70 px-3 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-slate-400 text-sm">📄</span>
          <span className="font-mono text-xs text-slate-300 truncate">{filepath}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {lang && (
            <span className="text-xs bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded">
              {lang}
            </span>
          )}
          {content && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              {expanded ? "收起" : "预览"}
            </button>
          )}
        </div>
      </div>

      {/* Code preview */}
      {expanded && content && (
        <pre className="bg-slate-900 text-slate-300 text-xs p-3 overflow-x-auto max-h-64 overflow-y-auto leading-relaxed">
          {preview}
          {hasMore && (
            <span className="text-slate-500 block mt-1">…（更多内容已省略）</span>
          )}
        </pre>
      )}
    </div>
  );
}
