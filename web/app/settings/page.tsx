"use client";

import { useEffect, useState } from "react";
import { ProfileTab } from "./components/ProfileTab";
import { CEOTab } from "./components/CEOTab";
import { APIKeysTab } from "./components/APIKeysTab";
import { ModelsTab } from "./components/ModelsTab";
import { MCPTab } from "./components/MCPTab";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TabKey = "profile" | "ceo" | "apikeys" | "models" | "mcp";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "profile", label: "用户画像",    icon: "👤" },
  { key: "ceo",     label: "CEO 配置",    icon: "🤖" },
  { key: "apikeys", label: "API Key",     icon: "🔑" },
  { key: "models",  label: "模型",        icon: "⚡" },
  { key: "mcp",     label: "MCP 工具",    icon: "🔧" },
];

const EMPTY_PROFILE = {
  name: "",
  role: "",
  technical_level: "technical" as const,
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
        <div className="text-slate-400 text-sm">加载设置中…</div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">系统设置</h1>
        <p className="text-slate-400 text-sm mt-1">
          配置 Agent 行为、用户画像、API 凭证和模型路由。所有设置持久化到数据库，无需重启服务。
        </p>
      </div>

      <div className="flex gap-8">
        {/* Sidebar tabs */}
        <nav className="w-44 shrink-0 space-y-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`w-full text-left flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                activeTab === t.key
                  ? "bg-blue-600/20 text-blue-300 border border-blue-500/30"
                  : "text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              <span>{t.icon}</span>
              <span>{t.label}</span>
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
