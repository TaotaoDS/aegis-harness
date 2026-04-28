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
  onDeleteNode?: (nodeId: string) => void | Promise<void>;
  onRelink?: () => void | Promise<void>;
  relinking?: boolean;
  relinkMsg?: string;
}

// Node colours — adding "web" for externally-saved web search results
const NODE_COLORS_WITH_WEB: Record<string, string> = {
  document: "#3b82f6",
  concept:  "#8b5cf6",
  tag:      "#10b981",
  entity:   "#f59e0b",
  solution: "#06b6d4",
  web:      "#ec4899",   // pink — visually distinct from internal nodes
};

// ---------------------------------------------------------------------------
// Visual constants
// ---------------------------------------------------------------------------

const NODE_COLORS = NODE_COLORS_WITH_WEB;
const FALLBACK_COLOR = "#64748b";

const LINK_COLOR_DARK  = "rgba(148,163,184,0.25)";
const LINK_COLOR_LIGHT = "rgba(100,116,139,0.30)";
const LINK_ACTIVE      = "rgba(139,92,246,0.75)";

// Semantic similarity edges get warmer colors to distinguish them from
// hard structural edges (contains_concept / web).
const LINK_SEMANTIC_DARK  = "rgba(251,146,60,0.45)";   // orange — semantically_related
const LINK_RELATED_DARK   = "rgba(167,243,208,0.45)";  // mint  — related_concept
const LINK_SEMANTIC_LIGHT = "rgba(234,88,12,0.35)";
const LINK_RELATED_LIGHT  = "rgba(16,185,129,0.40)";

function linkColor(link: GraphLink, active: boolean, isDark: boolean): string {
  if (active) return LINK_ACTIVE;
  if (link.relationship_type === "semantically_related") {
    return isDark ? LINK_SEMANTIC_DARK : LINK_SEMANTIC_LIGHT;
  }
  if (link.relationship_type === "related_concept") {
    return isDark ? LINK_RELATED_DARK : LINK_RELATED_LIGHT;
  }
  return isDark ? LINK_COLOR_DARK : LINK_COLOR_LIGHT;
}

function linkWidth(link: GraphLink, active: boolean): number {
  if (active) return 2.5;
  // Similarity edges: width proportional to weight (0.72–1.0 → 1.0–2.2px)
  if (link.relationship_type === "semantically_related" || link.relationship_type === "related_concept") {
    return 0.8 + (link.weight ?? 0.75) * 1.8;
  }
  return 1.0;
}

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
  onDeleteNode,
  onRelink,
  relinking,
  relinkMsg,
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

  const linkColorCb = useCallback(
    (link: object) => {
      const l = link as GraphLink;
      const src = typeof l.source === "string" ? l.source : l.source.id;
      const tgt = typeof l.target === "string" ? l.target : l.target.id;
      const active = src === selectedNodeId || tgt === selectedNodeId;
      return linkColor(l, active, isDark);
    },
    [selectedNodeId, isDark]
  );

  const linkWidthCb = useCallback(
    (link: object) => {
      const l = link as GraphLink;
      const src = typeof l.source === "string" ? l.source : l.source.id;
      const tgt = typeof l.target === "string" ? l.target : l.target.id;
      const active = src === selectedNodeId || tgt === selectedNodeId;
      return linkWidth(l, active);
    },
    [selectedNodeId]
  );

  return (
    <div className="flex flex-col h-full">
      {/* Graph toolbar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-stone-200 dark:border-slate-800 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 shrink-0">{t.knowledge.graphTitle}</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-700
                           border border-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:border-violet-700/40 shrink-0">
            {t.knowledge.nodesAndEdges(nodes.length, links.length)}
          </span>
          {relinkMsg && (
            <span className="text-[10px] text-emerald-600 dark:text-emerald-400 truncate">{relinkMsg}</span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {onRelink && (
            <button
              onClick={onRelink}
              disabled={relinking || loading}
              title="Analyze semantic similarity across all nodes and create related edges"
              className="text-xs px-2 py-1 rounded
                         text-amber-600 hover:text-white hover:bg-amber-600
                         dark:text-amber-400 dark:hover:text-white dark:hover:bg-amber-600
                         border border-amber-400/50 dark:border-amber-600/50
                         transition-colors disabled:opacity-40"
            >
              {relinking ? t.knowledge.relinking : t.knowledge.relink}
            </button>
          )}
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
      </div>

      {/* Legend — include semantic edge types */}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-3 py-1.5 border-b border-stone-200 dark:border-slate-800 shrink-0">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1 text-[10px] text-slate-500 dark:text-slate-500">
            <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
        <span className="flex items-center gap-1 text-[10px] text-slate-400 dark:text-slate-500 border-l border-slate-300 dark:border-slate-700 pl-2 ml-1">
          <span className="w-4 h-0.5 inline-block rounded" style={{ backgroundColor: "rgba(251,146,60,0.8)" }} />
          similar
        </span>
        <span className="flex items-center gap-1 text-[10px] text-slate-400 dark:text-slate-500">
          <span className="w-4 h-0.5 inline-block rounded" style={{ backgroundColor: "rgba(16,185,129,0.8)" }} />
          concept↔
        </span>
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
            linkColor={linkColorCb}
            linkWidth={linkWidthCb}
            onNodeClick={handleClick}
            nodeLabel={(n) => (n as GraphNode).title}
            linkLabel={(l) => (l as GraphLink).relationship_type}
            cooldownTicks={80}
            d3AlphaDecay={0.03}
            d3VelocityDecay={0.4}
          />
        )}
      </div>

      {/* Selected node info strip — with delete action */}
      {selectedNodeId && (
        <div className="shrink-0 border-t border-stone-200 dark:border-slate-800 px-3 py-2 text-xs
                        text-slate-600 dark:text-slate-400 bg-violet-50/40 dark:bg-violet-900/10
                        flex items-center justify-between gap-2">
          <div className="min-w-0 truncate">
            <span className="text-slate-900 dark:text-slate-200 font-medium">{t.knowledge.selected}</span>
            {nodes.find((n) => n.id === selectedNodeId)?.title ?? selectedNodeId}
            <span className="ml-2 text-slate-500">
              {t.knowledge.contextInjected(highlightedIds.size - 1)}
            </span>
          </div>
          {onDeleteNode && (
            <button
              onClick={() => {
                const node = nodes.find((n) => n.id === selectedNodeId);
                if (!node) return;
                if (window.confirm(t.knowledge.deleteConfirm(node.title))) {
                  onDeleteNode(selectedNodeId);
                }
              }}
              title={t.knowledge.deleteNode}
              className="shrink-0 text-[10px] px-2 py-0.5 rounded
                         text-red-600 hover:text-white hover:bg-red-600
                         dark:text-red-400 dark:hover:text-white dark:hover:bg-red-600
                         border border-red-300 dark:border-red-700/50
                         transition-colors"
            >
              ✕ {t.knowledge.deleteNode}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
