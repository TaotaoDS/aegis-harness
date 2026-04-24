"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n";

export interface UserProfile {
  name: string;
  role: string;
  technical_level: "technical" | "semi_technical" | "non_technical";
  language: string;
  notes: string;
}

const TECH_LEVEL_BADGES = {
  technical:     "bg-blue-900/50 text-blue-300 border-blue-700",
  semi_technical: "bg-yellow-900/50 text-yellow-300 border-yellow-700",
  non_technical:  "bg-purple-900/50 text-purple-300 border-purple-700",
};

interface Props {
  initial: UserProfile;
  onSave: (profile: UserProfile) => Promise<void>;
}

export function ProfileTab({ initial, onSave }: Props) {
  const t = useT();
  const [form, setForm] = useState<UserProfile>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");

  const TECH_LEVELS: {
    value: "technical" | "semi_technical" | "non_technical";
    label: string;
    badge: string;
    desc: string;
  }[] = [
    {
      value: "technical",
      label: t.profile.technical,
      badge: TECH_LEVEL_BADGES.technical,
      desc: t.profile.technicalDesc,
    },
    {
      value: "semi_technical",
      label: t.profile.semiTechnical,
      badge: TECH_LEVEL_BADGES.semi_technical,
      desc: t.profile.semiTechnicalDesc,
    },
    {
      value: "non_technical",
      label: t.profile.nonTechnical,
      badge: TECH_LEVEL_BADGES.non_technical,
      desc: t.profile.nonTechnicalDesc,
    },
  ];

  const update = (key: keyof UserProfile, val: string) => {
    setForm((f) => ({ ...f, [key]: val }));
    setSaved(false);
    setSaveError("");
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      setSaveError("");
      await onSave(form);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : t.profile.saveError);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">{t.profile.title}</h2>
        <p className="text-slate-400 text-sm">
          {t.profile.subtitle}
        </p>
      </div>

      {/* Name + Role */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">
            {t.profile.name}
          </label>
          <input
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
            placeholder={t.profile.namePlaceholder}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">
            {t.profile.role}
          </label>
          <input
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
            value={form.role}
            onChange={(e) => update("role", e.target.value)}
            placeholder={t.profile.rolePlaceholder}
          />
        </div>
      </div>

      {/* Technical level */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          {t.profile.techLevel}
        </label>
        <div className="grid grid-cols-3 gap-3">
          {TECH_LEVELS.map((lvl) => (
            <button
              key={lvl.value}
              onClick={() => update("technical_level", lvl.value)}
              className={`rounded-xl border p-4 text-left transition-all ${
                form.technical_level === lvl.value
                  ? "border-blue-500 bg-blue-900/30 ring-1 ring-blue-500"
                  : "border-slate-700 bg-slate-800/50 hover:border-slate-500"
              }`}
            >
              <span
                className={`inline-block text-xs font-semibold px-2 py-0.5 rounded border ${lvl.badge} mb-2`}
              >
                {lvl.label}
              </span>
              <p className="text-xs text-slate-400 leading-snug">{lvl.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Language */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">
          {t.profile.language}
        </label>
        <select
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
          value={form.language}
          onChange={(e) => update("language", e.target.value)}
        >
          <option value="auto">{t.profile.langAuto}</option>
          <option value="zh">{t.profile.langZh}</option>
          <option value="en">English</option>
          <option value="ja">日本語</option>
          <option value="ko">한국어</option>
        </select>
        <p className="text-xs text-slate-500 mt-1">
          {t.profile.langHint}
        </p>
      </div>

      {/* Notes */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">
          {t.profile.notes}
        </label>
        <textarea
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500 resize-none"
          rows={3}
          value={form.notes}
          onChange={(e) => update("notes", e.target.value)}
          placeholder={t.profile.notesPlaceholder}
        />
      </div>

      {saveError && (
        <div className="bg-red-950/60 border border-red-800 rounded-lg px-4 py-3 space-y-1">
          <p className="text-red-300 text-sm font-medium">⚠️ {saveError}</p>
          <p className="text-red-400/80 text-xs">{t.profile.saveErrorHint}</p>
        </div>
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        className={`px-5 py-2 rounded-lg text-sm font-medium transition-colors ${
          saved
            ? "bg-green-600 text-white"
            : "bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
        }`}
      >
        {saving ? t.profile.saving : saved ? t.profile.saved : t.profile.saveBtn}
      </button>
    </div>
  );
}
