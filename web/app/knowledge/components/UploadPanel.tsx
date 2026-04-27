"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type UploadStatus = "idle" | "uploading" | "polling" | "done" | "error";

type StageKey = "queued" | "parsing" | "extracting_content" | "extracting_concepts" | "building_graph" | "completed";

interface IngestStage {
  key: StageKey;
  pct: number;   // progress threshold to consider this stage "reached"
}

const STAGES: IngestStage[] = [
  { key: "queued",              pct: 0   },
  { key: "parsing",             pct: 15  },
  { key: "extracting_content",  pct: 35  },
  { key: "extracting_concepts", pct: 60  },
  { key: "building_graph",      pct: 80  },
  { key: "completed",           pct: 100 },
];

interface Props {
  onUploaded: (nodeId: string, filename: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function UploadPanel({ onUploaded }: Props) {
  const t = useT();
  const inputRef                 = useRef<HTMLInputElement>(null);
  const pollRef                  = useRef<ReturnType<typeof setInterval> | null>(null);
  const [dragging,  setDrag]     = useState(false);
  const [status,    setStatus]   = useState<UploadStatus>("idle");
  const [lastFile,  setLast]     = useState<string | null>(null);
  const [errMsg,    setErr]      = useState<string | null>(null);
  const [nodeId,    setNodeId]   = useState<string | null>(null);
  const [progress,  setProgress] = useState(0);
  const [ingestKey, setIngestKey] = useState<string>("queued");

  // Current active stage index
  const activeStageIdx = STAGES.findLastIndex((s) => progress >= s.pct);

  // ── polling ──────────────────────────────────────────────────────────────
  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const startPoll = useCallback((nid: string, fname: string) => {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/proxy/knowledge/nodes/${nid}`, { cache: "no-store" });
        if (!res.ok) return;
        const node = await res.json();
        const meta  = node.node_metadata ?? {};
        const pct   = typeof meta.progress === "number" ? meta.progress : 0;
        const key   = meta.ingest_status ?? "queued";
        setProgress(pct);
        setIngestKey(key);

        if (key === "completed" || pct >= 100) {
          stopPoll();
          setStatus("done");
          onUploaded(nid, fname);
        } else if (key === "failed") {
          stopPoll();
          setStatus("error");
          setErr(meta.error ?? "摄取失败，请重试");
        }
      } catch { /* network hiccup — keep polling */ }
    }, 2000);
  }, [stopPoll, onUploaded]);

  useEffect(() => () => stopPoll(), [stopPoll]);

  // ── upload ────────────────────────────────────────────────────────────────
  async function upload(file: File) {
    setStatus("uploading");
    setErr(null);
    setLast(file.name);
    setProgress(0);
    setIngestKey("queued");

    const fd = new FormData();
    fd.append("file", file);
    fd.append("workspace_id", "default");

    try {
      const res = await fetch("/api/proxy/knowledge/upload", { method: "POST", body: fd });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail ?? `HTTP ${res.status}`);
      }
      const { node_id } = await res.json();
      setNodeId(node_id);
      setStatus("polling");
      startPoll(node_id, file.name);
    } catch (e) {
      setStatus("error");
      setErr(String(e));
    }
  }

  function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    upload(files[0]);
  }

  function reset() {
    stopPoll();
    setStatus("idle");
    setErr(null);
    setNodeId(null);
    setProgress(0);
    setIngestKey("queued");
  }

  // ── render helpers ────────────────────────────────────────────────────────
  const isActive = status === "uploading" || status === "polling";

  return (
    <div className="px-3 py-2 border-b border-stone-200 dark:border-slate-800 shrink-0">
      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files); }}
        onClick={() => !isActive && inputRef.current?.click()}
        className={`
          flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-dashed
          transition-colors text-xs select-none
          ${dragging
            ? "border-blue-400 bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300"
            : isActive
              ? "border-stone-300 bg-stone-100 text-slate-500 cursor-default dark:border-slate-700 dark:bg-slate-800/40 dark:text-slate-400"
              : status === "done"
                ? "border-green-500/50 bg-green-50 text-green-700 cursor-pointer dark:bg-green-900/10 dark:text-green-300 dark:border-green-600/50"
                : status === "error"
                  ? "border-red-500/50 bg-red-50 text-red-700 cursor-pointer dark:bg-red-900/10 dark:text-red-300 dark:border-red-600/50"
                  : "border-stone-300 bg-stone-50 text-slate-500 hover:border-blue-500/60 hover:text-slate-700 cursor-pointer dark:border-slate-700 dark:bg-slate-800/20 dark:text-slate-400 dark:hover:text-slate-300"
          }
        `}
      >
        {status === "uploading" ? (
          <>
            <span className="w-3 h-3 rounded-full border-2 border-blue-400 border-t-transparent animate-spin shrink-0" />
            <span>{t.knowledge.uploading} <span className="text-blue-300">{lastFile}</span>…</span>
          </>
        ) : status === "polling" ? (
          <>
            <span className="w-3 h-3 rounded-full border-2 border-violet-400 border-t-transparent animate-spin shrink-0" />
            <span className="truncate max-w-[160px]">{lastFile}</span>
          </>
        ) : status === "done" ? (
          <>
            <span className="text-green-400 shrink-0">✓</span>
            <span className="truncate max-w-[170px]">{lastFile}</span>
          </>
        ) : status === "error" ? (
          <>
            <span className="text-red-400 shrink-0">✕</span>
            <span className="truncate max-w-[170px]">{errMsg}</span>
          </>
        ) : (
          <>
            <span>📄</span>
            <span>{t.knowledge.uploadHint} <span className="text-slate-700 dark:text-slate-300 font-medium">{t.knowledge.uploadFormats}</span></span>
          </>
        )}
      </div>

      {/* Progress stepper — visible while polling or done */}
      {(status === "polling" || status === "done") && (
        <div className="mt-2 px-1">
          {/* Progress bar */}
          <div className="w-full h-1 bg-stone-200 dark:bg-slate-700 rounded-full overflow-hidden mb-2">
            <div
              className="h-full bg-violet-500 rounded-full transition-all duration-700"
              style={{ width: `${Math.max(progress, 5)}%` }}
            />
          </div>

          {/* Stage pills */}
          <div className="flex items-center gap-0.5">
            {STAGES.map((stage, i) => {
              const reached  = i <= activeStageIdx;
              const isCurrent = i === activeStageIdx && status === "polling";
              return (
                <div key={stage.key} className="flex items-center gap-0.5 min-w-0">
                  {i > 0 && (
                    <div className={`w-3 h-px shrink-0 ${reached ? "bg-violet-500" : "bg-stone-300 dark:bg-slate-700"}`} />
                  )}
                  <div className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium whitespace-nowrap transition-colors ${
                    isCurrent
                      ? "bg-violet-100 text-violet-700 border border-violet-300 dark:bg-violet-700/40 dark:text-violet-200 dark:border-violet-600/50"
                      : reached
                        ? "text-violet-600 dark:text-violet-300"
                        : "text-slate-400 dark:text-slate-600"
                  }`}>
                    {isCurrent && (
                      <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse shrink-0" />
                    )}
                    {reached && !isCurrent && (
                      <span className="text-[8px] text-violet-500 dark:text-violet-400">✓</span>
                    )}
                    {t.knowledge.stages[stage.key]}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Reset after done/error */}
      {(status === "done" || status === "error") && (
        <button
          onClick={reset}
          className="mt-1.5 text-[10px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-300 transition-colors"
        >
          {t.knowledge.uploadAnother}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.txt"
        className="hidden"
        onChange={(e) => onFiles(e.target.files)}
      />
    </div>
  );
}
