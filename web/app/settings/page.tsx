"use client";

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n";
import { ProfileTab, UserProfile } from "./components/ProfileTab";
import { CEOTab } from "./components/CEOTab";
import { APIKeysTab } from "./components/APIKeysTab";
import { ModelsTab } from "./components/ModelsTab";
import { MCPTab } from "./components/MCPTab";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TabKey = "profile" | "ceo" | "apikeys" | "models" | "mcp";

const TAB_ICONS: Record<TabKey, string> = {
  profile: "👤",
  ceo:     "🤖",
  apikeys: "🔑",
  models:  "⚡",
  mcp:     "🔧",
};

const EMPTY_PROFILE: UserProfile = {
  name: "",
  role: "",
  technical_level: "technical",
  language: "auto",
  notes: "",
};

const EMPTY_CEO = {
  agent_name: "CEO",
  system_prompt_prefix: "",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiGet(key: string) {
  const res = await fetch(`/api/proxy/settings/${key}`);
  if (!res.ok) return null;
  const d = await res.json();
  return d?.value ?? null;
}

async function apiPut(key: string, value: unknown) {
  const res = await fetch(`/api/proxy/settings/${key}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) throw new Error(`Failed to save ${key}`);
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const t = useT();
  const [activeTab, setActiveTab] = useState<TabKey>("profile");
  const [loading, setLoading] = useState(true);

  // Settings state
  const [profile, setProfile] = useState(EMPTY_PROFILE);
  const [ceoConfig, setCeoConfig] = useState(EMPTY_CEO);
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [modelConfig, setModelConfig] = useState<{ default_model?: string }>({});
  const [mcpServers, setMcpServers] = useState<unknown[]>([]);

  // Load all settings on mount
  useEffect(() => {
    Promise.all([
      apiGet("user_profile"),
      apiGet("ceo_config"),
      apiGet("api_keys"),
      apiGet("model_config"),
      fetch("/api/proxy/mcp/servers").then((r) => r.ok ? r.json() : []).catch(() => []),
    ])
      .then(([p, c, k, m, mcp]) => {
        if (p) setProfile({ ...EMPTY_PROFILE, ...p });
        if (c) setCeoConfig({ ...EMPTY_CEO, ...c });
        if (k) setApiKeys(k);
        if (m) setModelConfig(m);
        if (Array.isArray(mcp)) setMcpServers(mcp);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-64">
        <div className="text-slate-400 text-sm">{t.settings.loading}</div>
      </div>
    );
  }

  const TABS: { key: TabKey; label: string; icon: string }[] = (
    Object.keys(TAB_ICONS) as TabKey[]
  ).map((key) => ({
    key,
    label: t.settings.tabs[key],
    icon: TAB_ICONS[key],
  }));

  return (
    <div className="max-w-4xl">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">{t.settings.title}</h1>
        <p className="text-slate-400 text-sm mt-1">
          {t.settings.subtitle}
        </p>
      </div>

      <div className="flex gap-8">
        {/* Sidebar tabs */}
        <nav className="w-44 shrink-0 space-y-1">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                activeTab === tab.key
                  ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                  : "text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>

        {/* Tab content */}
        <div className="flex-1 bg-slate-800/30 border border-slate-700 rounded-2xl p-6">
          {activeTab === "profile" && (
            <ProfileTab
              initial={profile}
              onSave={async (p) => {
                await apiPut("user_profile", p);
                setProfile(p);
              }}
            />
          )}
          {activeTab === "ceo" && (
            <CEOTab
              initial={ceoConfig}
              onSave={async (c) => {
                await apiPut("ceo_config", c);
                setCeoConfig(c);
              }}
            />
          )}
          {activeTab === "apikeys" && (
            <APIKeysTab
              initial={apiKeys}
              onSave={async (keys) => {
                await apiPut("api_keys", keys);
                // Re-fetch masked values to refresh the display
                const fresh = await apiGet("api_keys");
                if (fresh) setApiKeys(fresh);
              }}
            />
          )}
          {activeTab === "models" && (
            <ModelsTab
              initialConfig={modelConfig}
              onSaveConfig={async (c) => {
                await apiPut("model_config", c);
                setModelConfig(c);
              }}
            />
          )}
          {activeTab === "mcp" && (
            <MCPTab
              initial={mcpServers as never[]}
              onSave={(servers) => setMcpServers(servers)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
