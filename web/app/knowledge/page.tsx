"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { KnowledgeGraph, type GraphNode, type GraphLink } from "./components/KnowledgeGraph";
import { WorkspaceChat }  from "./components/WorkspaceChat";
import { UploadPanel }    from "./components/UploadPanel";
import { useT } from "@/lib/i18n";

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

async function fetchGraph(): Promise<GraphData> {
  const res = await fetch("/api/proxy/knowledge/graph", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Resizer constants
// ---------------------------------------------------------------------------

const LEFT_MIN_PX = 320;
const LEFT_MAX_PX = 720;
const LEFT_DEFAULT = 420;
const STORAGE_KEY = "ws-left-width";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function KnowledgePage() {
  const t = useT();
  const [graph,       setGraph]   = useState<GraphData>({ nodes: [], links: [] });
  const [loading,     setLoading] = useState(true);
  const [selectedId,  setSelId]   = useState<string | null>(null);

  const [ctxIds,    setCtxIds]    = useState<string[]>([]);
  const [ctxTitles, setCtxTitles] = useState<string[]>([]);

  // ── Resizable split-pane state ────────────────────────────────────────────
  const [leftWidth, setLeftWidth] = useState<number>(LEFT_DEFAULT);
  const [dragging,  setDragging]  = useState(false);
  const containerRef              = useRef<HTMLDivElement>(null);

  // Restore last width from localStorage
  useEffect(() => {
    try {
      const saved = parseInt(localStorage.getItem(STORAGE_KEY) ?? "", 10);
      if (Number.isFinite(saved) && saved >= LEFT_MIN_PX && saved <= LEFT_MAX_PX) {
        setLeftWidth(saved);
      }
    } catch { /* ignore */ }
  }, []);

  // Persist on change
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, String(leftWidth)); } catch { /* ignore */ }
  }, [leftWidth]);

  // Drag handlers
  useEffect(() => {
    if (!dragging) return;

    function onMove(e: MouseEvent) {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = e.clientX - rect.left;
      const clamped = Math.max(LEFT_MIN_PX, Math.min(LEFT_MAX_PX, next));
      setLeftWidth(clamped);
    }
    function onUp() { setDragging(false); }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);

    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  // ── Graph data ────────────────────────────────────────────────────────────
  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchGraph();
      setGraph(data);
    } catch (e) {
      console.error("[KnowledgePage] graph fetch failed", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadGraph(); }, [loadGraph]);

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelId(node.id);
    const neighbourIds = new Set<string>([node.id]);
    for (const link of graph.links) {
      const src = typeof link.source === "string" ? link.source : link.source.id;
      const tgt = typeof link.target === "string" ? link.target : link.target.id;
      if (src === node.id) neighbourIds.add(tgt);
      if (tgt === node.id) neighbourIds.add(src);
    }
    const ids    = [...neighbourIds];
    const titles = ids.map((id) => graph.nodes.find((n) => n.id === id)?.title ?? id);
    setCtxIds(ids);
    setCtxTitles(titles);
  }, [graph]);

  const highlightedIds = new Set(ctxIds);
  const selectedNode = selectedId
    ? (graph.nodes.find((n) => n.id === selectedId) ?? null)
    : null;

  const handleUploaded = useCallback((_nodeId: string, _filename: string) => {
    loadGraph();
  }, [loadGraph]);

  const handleAutoContext = useCallback((ids: string[], titles: string[]) => {
    setCtxIds(ids);
    setCtxTitles(titles);
    setSelId(null);
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      ref={containerRef}
      className="-mx-8 -my-8 flex overflow-hidden bg-[var(--bg-app)]"
      style={{ height: "calc(100vh - 0px)" }}
    >
      {/* ── Left panel: Upload + Graph ─────────────────────────────────── */}
      <div
        className="shrink-0 flex flex-col bg-white dark:bg-[#0b1220]
                   border-r border-stone-200 dark:border-slate-800"
        style={{ width: `${leftWidth}px`, height: "100%" }}
      >
        <div className="px-3 py-2.5 border-b border-stone-200 dark:border-slate-800 shrink-0">
          <h1 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <span>🤖</span> {t.workspace.title}
          </h1>
          <p className="text-[10px] text-slate-500 dark:text-slate-500 mt-0.5">
            {t.workspace.subtitle}
          </p>
        </div>

        <UploadPanel onUploaded={handleUploaded} />

        <div className="flex-1 overflow-hidden">
          <KnowledgeGraph
            nodes={graph.nodes}
            links={graph.links}
            selectedNodeId={selectedId}
            highlightedIds={highlightedIds}
            onNodeClick={handleNodeClick}
            onRefresh={loadGraph}
            loading={loading}
          />
        </div>
      </div>

      {/* ── Draggable resizer ──────────────────────────────────────────── */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽以调整左右面板宽度"
        onMouseDown={(e) => { e.preventDefault(); setDragging(true); }}
        onDoubleClick={() => setLeftWidth(LEFT_DEFAULT)}
        className={`resizer-handle shrink-0 w-1 ${dragging ? "is-dragging" : ""}`}
        style={{ height: "100%" }}
        title="拖拽调整宽度 · 双击重置"
      />

      {/* ── Right panel: Unified Workspace (QA + Tasks) ─────────────────── */}
      <div
        className="flex-1 flex flex-col bg-stone-50 dark:bg-[#0a0f1e]"
        style={{ height: "100%" }}
      >
        <WorkspaceChat
          selectedNode={selectedNode}
          contextNodeIds={ctxIds}
          contextTitles={ctxTitles}
          onAutoContext={handleAutoContext}
        />
      </div>
    </div>
  );
}
