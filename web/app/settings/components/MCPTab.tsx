"use client";

import { useState } from "react";

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
      flash("名称和 URL 不能为空", true); return;
    }
    setAdding(true);
    try {
      await apiPost("mcp/servers", {
        name: newName.trim(), url: newUrl.trim(), description: newDesc.trim(),
      });
      setNewName(""); setNewUrl(""); setNewDesc("");
      await refresh();
      flash("服务器已添加");
    } catch (e) {
      flash(`添加失败: ${String(e)}`, true);
    } finally {
      setAdding(false);
    }
  };

  // Remove server
  const handleRemove = async (id: string) => {
    try {
      await apiDelete(`mcp/servers/${id}`);
      await refresh();
      flash("已删除");
    } catch (e) {
      flash(`删除失败: ${String(e)}`, true);
    }
  };

  // Probe server
  const handleProbe = async (id: string) => {
    setProbingId(id);
    try {
      const result = await apiPost(`mcp/servers/${id}/probe`, {});
      await refresh();
      if (result.status === "connected") {
        flash(`连接成功，发现 ${result.tool_count ?? 0} 个工具`);
      } else {
        flash(`连接失败: ${result.error ?? "unknown"}`, true);
      }
    } catch (e) {
      flash(`探测失败: ${String(e)}`, true);
    } finally {
      setProbingId(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-white">MCP 工具服务器</h2>
        <p className="text-slate-400 text-xs mt-1">
          挂载外部 MCP 服务器，让 Agent 可以调用自定义工具（文件系统、搜索、数据库等）。
        </p>
      </div>

      {/* Feedback */}
      {error   && <div className="text-red-400 text-sm bg-red-900/20 border border-red-500/30 rounded-lg px-4 py-2">{error}</div>}
      {success && <div className="text-green-400 text-sm bg-green-900/20 border border-green-500/30 rounded-lg px-4 py-2">{success}</div>}

      {/* Add new server */}
      <div className="bg-slate-700/30 border border-slate-600 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-medium text-slate-200">添加新服务器</h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">名称 *</label>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="例如：文件系统工具"
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2
                         text-sm text-slate-100 placeholder-slate-500 focus:outline-none
                         focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">服务器 URL *</label>
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
          <label className="text-xs text-slate-400 mb-1 block">描述（可选）</label>
          <input
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder="此服务器提供什么功能？"
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
          {adding ? "添加中…" : "+ 添加服务器"}
        </button>
      </div>

      {/* Server list */}
      {servers.length === 0 ? (
        <div className="text-center text-slate-500 text-sm py-8">
          暂无已注册的 MCP 服务器。添加第一个服务器以开始使用。
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
                        已禁用
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
                      {srv.tools.slice(0, 8).map((t, i) => (
                        <span
                          key={i}
                          className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded"
                          title={t.description ?? ""}
                        >
                          {t.name}
                        </span>
                      ))}
                      {srv.tools.length > 8 && (
                        <span className="text-xs text-slate-500">
                          +{srv.tools.length - 8} 更多
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
                    {probingId === srv.id ? "探测中…" : "探测连接"}
                  </button>
                  <button
                    onClick={() => handleRemove(srv.id)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-red-900/30 hover:bg-red-900/50
                               text-red-400 border border-red-800/50 transition-colors"
                  >
                    删除
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
