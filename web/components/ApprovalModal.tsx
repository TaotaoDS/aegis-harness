"use client";

import { useState } from "react";
import type { PendingApproval } from "@/hooks/useApproval";
import { useT } from "@/lib/i18n";

interface Props {
  pending: PendingApproval;
  submitting: boolean;
  onRespond: (approved: boolean, note?: string) => void;
}

export function ApprovalModal({ pending, submitting, onRespond }: Props) {
  const t = useT();
  const [note, setNote] = useState("");

  const REASON_LABELS: Record<string, string> = {
    update_mode:    t.approval.update_mode,
    sensitive_file: t.approval.sensitive_file,
  };

  return (
    /* Full-screen backdrop — blocks all interaction underneath */
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[#0d1526] border border-yellow-600/50 rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        {/* Header */}
        <div className="bg-yellow-600/10 border-b border-yellow-600/30 px-6 py-4 flex items-center gap-3">
          <span className="text-2xl">🔐</span>
          <div>
            <h2 className="text-white font-semibold text-lg">{t.approval.title}</h2>
            <p className="text-yellow-400 text-sm">
              {REASON_LABELS[pending.reason] ?? pending.reason}
            </p>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          <p className="text-slate-300 text-sm leading-relaxed">
            {pending.description}
          </p>

          {/* Requirement (Update Mode) */}
          {pending.requirement && (
            <div className="bg-slate-800 rounded-lg px-4 py-3">
              <p className="text-xs text-slate-400 mb-1">{t.approval.changeReq}</p>
              <p className="text-slate-200 text-sm">{pending.requirement}</p>
            </div>
          )}

          {/* Sensitive filepath */}
          {pending.filepath && (
            <div className="bg-slate-800 rounded-lg px-4 py-3">
              <p className="text-xs text-slate-400 mb-1">{t.approval.targetFile}</p>
              <p className="font-mono text-yellow-300 text-sm">{pending.filepath}</p>
            </div>
          )}

          {/* Files to modify (Update Mode list) */}
          {pending.files_to_modify && pending.files_to_modify.length > 0 && (
            <div className="bg-slate-800 rounded-lg px-4 py-3">
              <p className="text-xs text-slate-400 mb-2">{t.approval.filesToModify}</p>
              <ul className="space-y-1">
                {pending.files_to_modify.map((f) => (
                  <li key={f} className="font-mono text-xs text-slate-300 flex items-center gap-2">
                    <span className="text-slate-500">›</span> {f}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Optional rejection note */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">
              {t.approval.noteLabel}
            </label>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t.approval.notePlaceholder}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 text-sm focus:outline-none focus:border-blue-500 transition-colors"
            />
          </div>
        </div>

        {/* Actions */}
        <div className="px-6 pb-5 flex gap-3">
          <button
            onClick={() => onRespond(false, note)}
            disabled={submitting}
            className="flex-1 py-2.5 rounded-xl border border-red-700 text-red-400 hover:bg-red-900/20 disabled:opacity-40 transition-colors text-sm font-medium"
          >
            {submitting ? t.approval.processing : t.approval.reject}
          </button>
          <button
            onClick={() => onRespond(true, note)}
            disabled={submitting}
            className="flex-1 py-2.5 rounded-xl bg-green-700 hover:bg-green-600 disabled:opacity-40 text-white transition-colors text-sm font-medium"
          >
            {submitting ? t.approval.processing : t.approval.approve}
          </button>
        </div>
      </div>
    </div>
  );
}
