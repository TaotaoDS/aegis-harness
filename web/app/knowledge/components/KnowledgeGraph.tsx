"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import dynamic from "next/dynamic";
import { useT } from "@/lib/i18n";

// react-force-graph-2d is canvas — must be client-only
const ForceGraph2D = dynamic(
  () => import("react-force-graph-2d"),
  { ssr: false }
);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GraphNode {
  id: string;
  node_type: string;
  title: string;
  content?: string | null;
  node_metadata?: Record<string, unknown>;
  has_embedding: boolean;
  // ForceGraph internal fields (injected at runtime)
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number;
  fy?: number;
}

export interface GraphLink {
  id: number;
  source: string | GraphNode;
  target: string | GraphNode;
  relationship_type: string;
  weight: number;
}

interface Props {
  nodes: GraphNode[];
  links: GraphLink[];
  selectedNodeId: string | null;
  highlightedIds: Set<string>;
  onNodeClick: (node: GraphNode) => void;
  onRefresh: () => void;
  loading: boolean;
}

// ---------------------------------------------------------------------------
// Visual constants
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  document: "#3b82f6",  // blue
  concept:  "#8b5cf6",  // violet
  tag:      "#10b981",  // green
  entity:   "#f59e0b",  // amber
  solution: "#06b6d4",  // cyan
};
const FALLBACK_COLOR = "#64748b";

const LINK_COLOR_DARK  = "rgba(148,163,184,0.25)";
const LINK_COLOR_LIGHT = "rgba(100,116,139,0.30)";
const LINK_ACTIVE      = "rgba(139,92,246,0.75)";

function nodeColor(node: GraphNode, selected: boolean, highlighted: boolean, isDark: boolean): string {
  if (selected)    return isDark ? "#ffffff" : "#0f172a";
  if (highlighted) return isDark ? "#e2e8f0" : "#334155";
  return NODE_COLORS[node.node_type] ?? FALLBACK_COLOR;
}

function nodeRadius(node: GraphNode, selected: boolean): number {
  const base = node.node_type === "document" ? 7 : 5;
  return selected ? base + 4 : base;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function KnowledgeGraph({
  nodes,
  links,
  selectedNodeId,
  highlightedIds,
  onNodeClick,
  onRefresh,
  loading,
}: Props) {
  const t = useT();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims]   = useState({ w: 0, h: 0 });
  const [ready, setReady] = useState(false);
  const [isDark, setIsDark] = useState(true);

  // Track theme by observing the `dark` class on <html>
  useEffect(() => {
    if (typeof document === "undefined") return;
    const update = () => setIsDark(document.documentElement.classList.contains("dark"));
    update();
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  // Track container size with ResizeObserver
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDims({ w: Math.floor(width), h: Math.floor(height) });
      setReady(true);
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const handleClick = useCallback(
    (node: object) => onNodeClick(node as GraphNode),
    [onNodeClick]
  );

  const paintNode = useCallback(
    (node: object, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const n        = node as GraphNode & { x: number; y: number };
      const selected = n.id === selectedNodeId;
      const hilit    = highlightedIds.has(n.id);
      const r        = nodeRadius(n, selected) / globalScale;
      const color    = nodeColor(n, selected, hilit, isDark);

      // Selection ring
      if (selected) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 3 / globalScale, 0, 2 * Math.PI);
        ctx.fillStyle = isDark ? "rgba(255,255,255,0.18)" : "rgba(15,23,42,0.12)";
        ctx.fill();
      }

      // Node circle
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();

      // Label for doc nodes or selected/hilit
      if (n.node_type === "document" || selected || (hilit && globalScale > 1.5)) {
        const label  = n.title.length > 18 ? n.title.slice(0, 16) + "…" : n.title;
        const fs     = Math.max(10 / globalScale, 3);
        ctx.font     = `${selected ? "bold " : ""}${fs}px sans-serif`;
        ctx.fillStyle = isDark
          ? (selected ? "#ffffff" : "rgba(226,232,240,0.85)")
          : (selected ? "#0f172a" : "rgba(30,41,59,0.85)");
        ctx.textAlign = "center";
        ctx.fillText(label, n.x, n.y + r + fs * 1.2);
      }
    },
    [selectedNodeId, highlightedIds, isDark]
  );

  const linkColor = useCallback(
    (link: object) => {
      const l = link as GraphLink;
      const src = typeof l.source === "string" ? l.source : l.source.id;
      const tgt = typeof l.target === "string" ? l.target : l.target.id;
      if (src === selectedNodeId || tgt === selectedNodeId) return LINK_ACTIVE;
      return isDark ? LINK_COLOR_DARK : LINK_COLOR_LIGHT;
    },
    [selectedNodeId, isDark]
  );

  const linkWidth = useCallback(
    (link: object) => {
      const l = link as GraphLink;
      const src = typeof l.source === "string" ? l.source : l.source.id;
      const tgt = typeof l.target === "string" ? l.target : l.target.id;
      return src === selectedNodeId || tgt === selectedNodeId ? 2 : 0.8;
    },
    [selectedNodeId]
  );

  return (
    <div className="flex flex-col h-full">
      {/* Graph toolbar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-stone-200 dark:border-slate-800 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">{t.knowledge.graphTitle}</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-700
                           border border-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:border-violet-700/40">
            {t.knowledge.nodesAndEdges(nodes.length, links.length)}
          </span>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="text-xs px-2 py-1 rounded
                     text-slate-500 hover:text-slate-900 hover:bg-stone-100
                     dark:text-slate-400 dark:hover:text-white dark:hover:bg-slate-800
                     transition-colors disabled:opacity-40"
        >
          {loading ? t.knowledge.refreshing : t.knowledge.refresh}
        </button>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-3 py-1.5 border-b border-stone-200 dark:border-slate-800 shrink-0">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1 text-[10px] text-slate-500 dark:text-slate-500">
            <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
      </div>

      {/* Canvas area */}
      <div ref={containerRef} className="flex-1 relative overflow-hidden">
        {nodes.length === 0 && !loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-400 dark:text-slate-500">
            <span className="text-3xl">🧠</span>
            <p className="text-xs">{t.knowledge.emptyGraph}</p>
          </div>
        )}
        {ready && dims.w > 0 && nodes.length > 0 && (
          <ForceGraph2D
            graphData={{ nodes, links }}
            width={dims.w}
            height={dims.h}
            backgroundColor="transparent"
            nodeCanvasObject={paintNode}
            nodeCanvasObjectMode={() => "replace"}
            linkColor={linkColor}
            linkWidth={linkWidth}
            onNodeClick={handleClick}
            nodeLabel={(n) => (n as GraphNode).title}
            linkLabel={(l) => (l as GraphLink).relationship_type}
            cooldownTicks={80}
            d3AlphaDecay={0.03}
            d3VelocityDecay={0.4}
          />
        )}
      </div>

      {/* Selected node info strip */}
      {selectedNodeId && (
        <div className="shrink-0 border-t border-stone-200 dark:border-slate-800 px-3 py-2 text-xs
                        text-slate-600 dark:text-slate-400 bg-violet-50/40 dark:bg-violet-900/10">
          <span className="text-slate-900 dark:text-slate-200 font-medium">{t.knowledge.selected}</span>
          {nodes.find((n) => n.id === selectedNodeId)?.title ?? selectedNodeId}
          <span className="ml-2 text-slate-500">
            {t.knowledge.contextInjected(highlightedIds.size - 1)}
          </span>
        </div>
      )}
    </div>
  );
}
