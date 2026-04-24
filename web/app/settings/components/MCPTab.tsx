"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MCPServer {
  id:          string;
  name:        string;
  url:         string;
  enabled:     boolean;
  description: string;
  status:      "connected" | "error" | "unknown";
  tools:       { name: string; description?: string }[];
  error:       string;
}

interface Props {
  initial: MCPServer[];
  onSave:  (servers: MCPServer[]) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiGet(path: string) {
  const res = await fetch(`/api/proxy/${path}`);
  if (!res.ok) return null;
  return res.json();
}

async function apiPost(path: string, body: unknown) {
  const res = await fetch(`/api/proxy/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiDelete(path: string) {
  const res = await fetch(`/api/proxy/${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

const STATUS_COLOR: Record<string, string> = {
  connected: "text-green-400",
  error:     "text-red-400",
  unknown:   "text-slate-400",
};

const STATUS_ICON: Record<string, string> = {
  connected: "●",
  error:     "●",
  unknown:   "○",
};

// ---------------------------------------------------------------------------
// MCPTab
// ---------------------------------------------------------------------------

export function MCPTab({ initial, onSave }: Props) {
  const t = useT();
  const [servers, setServers]   = useState<MCPServer[]>(initial);
  const [newName, setNewName]   = useState("");
  const [newUrl, setNewUrl]     = useState("");
  const [newDesc, setNewDesc]   = useState("");
  const [adding, setAdding]     = useState(false);
  const [probingId, setProbingId] = useState<string | null>(null);
  const [error, setError]       = useState("");
  const [success, setSuccess]   = useState("");

  const flash = (msg: string, isErr = false) => {
    if (isErr) { setError(msg); setTimeout(() => setError(""), 4000); }
    else       { setSuccess(msg); setTimeout(() => setSuccess(""), 3000); }
  };

  // Refresh list from backend
  const refresh = async () => {
    const data = await apiGet("mcp/servers");
    if (Array.isArray(data)) { setServers(data); onSave(data); }
  };

  // Add server
  const handleAdd = async () => {
    if (!newName.trim() || !newUrl.trim()) {
      flash(t.mcp.emptyError, true); return;
    }
    setAdding(true);
    try {
      await apiPost("mcp/servers", {
        name: newName.trim(), url: newUrl.trim(), description: newDesc.trim(),
      });
      setNewName(""); setNewUrl(""); setNewDesc("");
      await refresh();
      flash(t.mcp.addSuccess);
    } catch (e) {
      flash(t.mcp.addFailed(String(e)), true);
    } finally {
      setAdding(false);
    }
  };

  // Remove server
  const handleRemove = async (id: string) => {
    try {
      await apiDelete(`mcp/servers/${id}`);
      await refresh();
      flash(t.mcp.deleteSuccess);
    } catch (e) {
      flash(t.mcp.deleteFailed(String(e)), true);
    }
  };

  // Probe server
  const handleProbe = async (id: string) => {
    setProbingId(id);
    try {
      const result = await apiPost(`mcp/servers/${id}/probe`, {});
      await refresh();
      if (result.status === "connected") {
        flash(t.mcp.probeSuccess(result.tool_count ?? 0));
      } else {
        flash(t.mcp.probeFailed(result.error ?? "unknown"), true);
      }
    } catch (e) {
      flash(t.mcp.probeError(String(e)), true);
    } finally {
      setProbingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-white">{t.mcp.title}</h2>
        <p className="text-slate-400 text-xs mt-1">
          {t.mcp.subtitle}
        </p>
      </div>

      {/* Feedback */}
      {error   && <div className="text-red-400 text-sm bg-red-900/20 border border-red-500/30 rounded-lg px-4 py-2">{error}</div>}
      {success && <div className="text-green-400 text-sm bg-green-900/20 border border-green-500/30 rounded-lg px-4 py-2">{success}</div>}

      {/* Add new server */}
      <div className="bg-slate-700/30 border border-slate-600 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-medium text-slate-200">{t.mcp.addServer}</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t.mcp.nameLabel}</label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={t.mcp.namePlaceholder}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2
                         text-sm text-slate-100 placeholder-slate-500 focus:outline-none
                         focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t.mcp.urlLabel}</label>
            <input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="http://localhost:3001"
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2
                         text-sm text-slate-100 placeholder-slate-500 focus:outline-none
                         focus:border-blue-500"
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-slate-400 mb-1 block">{t.mcp.descLabel}</label>
          <input
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder={t.mcp.descPlaceholder}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2
                       text-sm text-slate-100 placeholder-slate-500 focus:outline-none
                       focus:border-blue-500"
          />
        </div>
        <button
          onClick={handleAdd}
          disabled={adding}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700
                     disabled:text-slate-500 text-white text-sm rounded-lg transition-colors"
        >
          {adding ? t.mcp.adding : t.mcp.addBtn}
        </button>
      </div>

      {/* Server list */}
      {servers.length === 0 ? (
        <div className="text-center text-slate-500 text-sm py-8">
          {t.mcp.empty}
        </div>
      ) : (
        <div className="space-y-3">
          {servers.map((srv) => (
            <div
              key={srv.id}
              className="bg-slate-700/30 border border-slate-600 rounded-xl p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs ${STATUS_COLOR[srv.status] ?? "text-slate-400"}`}>
                      {STATUS_ICON[srv.status] ?? "○"}
                    </span>
                    <span className="text-sm font-medium text-white truncate">{srv.name}</span>
                    {!srv.enabled && (
                      <span className="text-xs text-slate-500 bg-slate-700 px-2 py-0.5 rounded">
                        {t.mcp.disabled}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5 truncate">{srv.url}</div>
                  {srv.description && (
                    <div className="text-xs text-slate-500 mt-0.5">{srv.description}</div>
                  )}
                  {srv.error && (
                    <div className="text-xs text-red-400 mt-1">{srv.error}</div>
                  )}
                  {srv.tools.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {srv.tools.slice(0, 8).map((tool, i) => (
                        <span
                          key={i}
                          className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded"
                          title={tool.description ?? ""}
                        >
                          {tool.name}
                        </span>
                      ))}
                      {srv.tools.length > 8 && (
                        <span className="text-xs text-slate-500">
                          {t.mcp.more(srv.tools.length - 8)}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => handleProbe(srv.id)}
                    disabled={probingId === srv.id}
                    className="text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600
                               text-slate-300 disabled:text-slate-500 transition-colors"
                  >
                    {probingId === srv.id ? t.mcp.probing : t.mcp.probe}
                  </button>
                  <button
                    onClick={() => handleRemove(srv.id)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-red-900/30 hover:bg-red-900/50
                               text-red-400 border border-red-800/50 transition-colors"
                  >
                    {t.mcp.delete}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
