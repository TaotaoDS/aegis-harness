"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n";
import type { PendingApproval } from "@/hooks/useApproval";

interface Props {
  jobId:        string;
  pending:      PendingApproval;
  responded?:   { approved: boolean; note: string };
  expired?:     boolean;
  onResponded:  (approved: boolean, note?: string) => void;
}

export function InlineApprovalCard({ jobId, pending, responded, expired, onResponded }: Props) {
  const t = useT();
  const [note,       setNote]       = useState("");
  const [submitting, setSubmitting] = useState(false);

  const disabled = !!responded || !!expired;

  const REASON_LABELS: Record<string, string> = {
    update_mode:    t.approval.update_mode,
    sensitive_file: t.approval.sensitive_file,
  };

  const handleRespond = async (approved: boolean) => {
    if (submitting || disabled) return;
    setSubmitting(true);
    try {
      await fetch(`/api/proxy/jobs/${jobId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved, note: note.trim() }),
      });
      onResponded(approved, note.trim());
    } catch {
      // HITL gate times out gracefully on the backend
    } finally {
      setSubmitting(false);
    }
  };

  const borderColor = responded
    ? responded.approved
      ? "border-green-400/50 dark:border-green-700/40"
      : "border-red-400/50 dark:border-red-700/40"
    : expired
      ? "border-slate-300 dark:border-slate-700/40"
      : "border-yellow-400/60 dark:border-yellow-600/40";

  const bgColor = responded
    ? responded.approved
      ? "bg-green-50 dark:bg-green-900/10"
      : "bg-red-50 dark:bg-red-900/10"
    : expired
      ? "bg-slate-50 dark:bg-slate-800/30"
      : "bg-yellow-50 dark:bg-yellow-900/10";

  return (
    <div className={`rounded-xl border ${borderColor} ${bgColor} overflow-hidden text-xs w-full transition-colors`}>
      {/* Header */}
      <div className="px-3 py-2 border-b border-stone-200/50 dark:border-slate-700/30
                      flex items-center gap-2">
        {!disabled && (
          <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse shrink-0" />
        )}
        {responded && (
          <span className={`shrink-0 ${responded.approved ? "text-green-600 dark:text-green-400" : "text-red-500 dark:text-red-400"}`}>
            {responded.approved ? "✓" : "✕"}
          </span>
        )}
        <span className="text-xs font-medium text-yellow-700 dark:text-yellow-300">
          {t.inlineCards.approvalTitle}
        </span>
        <span className="text-[10px] text-slate-500 dark:text-slate-400">
          {REASON_LABELS[pending.reason] ?? pending.reason}
        </span>
        {responded && (
          <span className={`ml-auto text-[10px] font-medium ${
            responded.approved
              ? "text-green-600 dark:text-green-400"
              : "text-red-500 dark:text-red-400"
          }`}>
            {responded.approved ? t.inlineCards.approved : t.inlineCards.rejected}
          </span>
        )}
        {expired && (
          <span className="ml-auto text-[10px] text-slate-400">{t.inlineCards.expired}</span>
        )}
        {!disabled && (
          <span className="ml-auto text-[10px] text-yellow-600/70 dark:text-yellow-400/60">
            {t.inlineCards.pipelineWaiting}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="px-3 py-2.5 space-y-2">
        <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
          {pending.description}
        </p>

        {pending.requirement && (
          <div className="bg-white/60 dark:bg-slate-800/50 rounded-lg px-2.5 py-1.5">
            <p className="text-[10px] text-slate-400 mb-0.5">{t.approval.changeReq}</p>
            <p className="text-xs text-slate-700 dark:text-slate-300">{pending.requirement}</p>
          </div>
        )}

        {pending.filepath && (
          <div className="bg-white/60 dark:bg-slate-800/50 rounded-lg px-2.5 py-1.5">
            <p className="text-[10px] text-slate-400 mb-0.5">{t.approval.targetFile}</p>
            <p className="font-mono text-xs text-yellow-700 dark:text-yellow-300">{pending.filepath}</p>
          </div>
        )}

        {pending.files_to_modify && pending.files_to_modify.length > 0 && (
          <div className="bg-white/60 dark:bg-slate-800/50 rounded-lg px-2.5 py-1.5">
            <p className="text-[10px] text-slate-400 mb-1">{t.approval.filesToModify}</p>
            <ul className="space-y-0.5">
              {pending.files_to_modify.map((f) => (
                <li key={f} className="font-mono text-[10px] text-slate-600 dark:text-slate-400 flex items-center gap-1.5">
                  <span className="text-slate-400">›</span> {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Responded state: show the decision note */}
        {responded?.note && (
          <div className={`rounded-lg px-2.5 py-1.5 text-xs ${
            responded.approved
              ? "bg-green-100/60 dark:bg-green-900/20 text-slate-600 dark:text-slate-400"
              : "bg-red-100/60 dark:bg-red-900/20 text-slate-600 dark:text-slate-400"
          }`}>
            {responded.note}
          </div>
        )}
      </div>

      {/* Actions (active state) */}
      {!disabled && (
        <div className="px-3 pb-3 space-y-2">
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t.inlineCards.notePlaceholder}
            disabled={submitting}
            className="w-full bg-white dark:bg-slate-800 border border-stone-300 dark:border-slate-600
                       rounded-lg px-2.5 py-1.5 text-xs text-slate-700 dark:text-slate-200
                       outline-none focus:border-yellow-500 transition-colors
                       disabled:opacity-50 placeholder-slate-400 dark:placeholder-slate-500"
          />
          <div className="flex gap-2">
            <button
              onClick={() => handleRespond(false)}
              disabled={submitting}
              className="flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors
                         border border-red-400 dark:border-red-700 text-red-600 dark:text-red-400
                         hover:bg-red-50 dark:hover:bg-red-900/20
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {submitting ? t.approval.processing : t.inlineCards.rejectBtn}
            </button>
            <button
              onClick={() => handleRespond(true)}
              disabled={submitting}
              className="flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors
                         bg-green-600 hover:bg-green-500 text-white
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {submitting ? t.approval.processing : t.inlineCards.approveBtn}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
