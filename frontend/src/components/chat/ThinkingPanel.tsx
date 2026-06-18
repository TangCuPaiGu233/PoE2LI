"use client";

import { useState, useEffect, useRef } from "react";

// ── Types ──

export interface ToolCallInfo {
  id: string;
  name: string;
  label: string;
  args: Record<string, unknown>;
  status: "pending" | "success" | "error";
  resultPreview?: string;
}

interface ThinkingPanelProps {
  reasoning?: string;
  toolCalls?: ToolCallInfo[];
  isStreaming?: boolean;
  showPending?: boolean;
}

// ── Constants ──

const TOOL_ICONS: Record<string, string> = {
  search_game: "🔍",
  rag_search: "📚",
  decode_pob: "⚙️",
  trade_search: "🛒",
  recommend: "📊",
  entity_resolve: "🏷️",
};

// ── Helpers ──

function getToolTitle(tc: ToolCallInfo): string {
  const q = tc.args.query || tc.args.code || tc.args.user_msg;
  if (q) {
    const s = String(q);
    return `${tc.label}"${s.length > 30 ? s.slice(0, 30) + "…" : s}"`;
  }
  return tc.label;
}

function getToolSubtitle(tc: ToolCallInfo): string {
  if (!tc.resultPreview) return "";
  const matchCount = tc.resultPreview.match(/匹配[：:]\s*(\d+)/);
  if (matchCount) return `找到 ${matchCount[1]} 个结果`;
  const chunkCount = tc.resultPreview.match(/chunk_count[：:]\s*(\d+)/);
  if (chunkCount) return `参考 ${chunkCount[1]} 篇资料`;
  const entitiesFound = tc.resultPreview.match(/found\s+(\d+)/i);
  if (entitiesFound) return `找到 ${entitiesFound[1]} 个结果`;
  return tc.resultPreview.length > 60
    ? tc.resultPreview.slice(0, 60) + "…"
    : tc.resultPreview;
}

function buildSummary(
  toolCalls: ToolCallInfo[],
  hasReasoning: boolean
): string {
  const parts: string[] = [];
  if (hasReasoning) parts.push("推理分析");

  const toolLabels = [...new Set(toolCalls.map((t) => t.label))];
  if (toolLabels.length > 0) {
    parts.push(`调用了 ${toolLabels.join("、")}`);
  }

  const successCount = toolCalls.filter((t) => t.status === "success").length;
  if (successCount > 0) {
    parts.push(`${successCount} 个工具返回结果`);
  }

  return parts.length > 0 ? parts.join("，") : "思考过程";
}

// ── Sub-components ──

function Spinner() {
  return (
    <span
      className="inline-block w-3 h-3 rounded-full border-2 border-[var(--ninja-accent)] border-t-transparent"
      style={{ animation: "spin 0.8s linear infinite" }}
    />
  );
}

function StatusIcon({ status }: { status: ToolCallInfo["status"] }) {
  if (status === "pending") return <Spinner />;
  if (status === "error")
    return (
      <span className="text-xs text-red-400 font-medium">✗</span>
    );
  return (
    <span className="text-xs text-[var(--ninja-accent)] font-medium">✓</span>
  );
}

function ToolCallCard({ tc }: { tc: ToolCallInfo }) {
  const [expanded, setExpanded] = useState(false);
  const icon = TOOL_ICONS[tc.name] || "🔧";
  const title = getToolTitle(tc);
  const subtitle = getToolSubtitle(tc);

  const hasDetails =
    (tc.args && Object.keys(tc.args).length > 0) || tc.resultPreview;

  return (
    <div
      className={`tool-card ${tc.status === "pending" ? "tool-card-pending" : ""}`}
    >
      {/* Header row */}
      <button
        type="button"
        className="w-full flex items-center gap-2 text-left cursor-pointer"
        onClick={() => hasDetails && setExpanded(!expanded)}
      >
        <span className="text-sm shrink-0">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-[var(--ninja-text-muted)] truncate">
            {title}
          </div>
          {subtitle && (
            <div
              className={`text-[11px] mt-0.5 ${
                tc.status === "error"
                  ? "text-red-400/70"
                  : "text-[var(--ninja-text-dim)]"
              }`}
            >
              <span className="inline-flex items-center gap-1.5">
                <StatusIcon status={tc.status} />
                {subtitle}
              </span>
            </div>
          )}
          {!subtitle && tc.status === "pending" && (
            <div className="text-[11px] mt-0.5 text-[var(--ninja-accent)]/50">
              <span className="inline-flex items-center gap-1.5">
                <Spinner />
                处理中…
              </span>
            </div>
          )}
        </div>
        {hasDetails && (
          <span
            className={`text-[10px] text-[var(--ninja-text-dim)] shrink-0 transition-transform duration-200 ${
              expanded ? "rotate-90" : ""
            }`}
          >
            ▶
          </span>
        )}
      </button>

      {/* Expandable details */}
      {expanded && hasDetails && (
        <div className="mt-2 pt-2 border-t border-[var(--ninja-border)] text-[11px] space-y-1.5">
          {tc.args && Object.keys(tc.args).length > 0 && (
            <div>
              <span className="text-[var(--ninja-text-dim)]">参数：</span>
              <span className="text-[var(--ninja-text-muted)] font-mono">
                {JSON.stringify(tc.args, null, 0).slice(0, 200)}
              </span>
            </div>
          )}
          {tc.resultPreview && (
            <div>
              <span className="text-[var(--ninja-text-dim)]">结果：</span>
              <span className="text-[var(--ninja-text-muted)] whitespace-pre-wrap">
                {tc.resultPreview.slice(0, 300)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Component ──

export default function ThinkingPanel({
  reasoning,
  toolCalls,
  isStreaming,
  showPending,
}: ThinkingPanelProps) {
  const [open, setOpen] = useState(false);
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const autoCollapsedRef = useRef(false);

  const hasToolCalls = !!(toolCalls && toolCalls.length > 0);
  const hasReasoning = !!(reasoning && reasoning.trim());
  const hasContent = hasToolCalls || hasReasoning || showPending;

  // Smart folding: auto-expand during streaming, auto-collapse after done
  useEffect(() => {
    if (isStreaming && hasContent) {
      setOpen(true);
      autoCollapsedRef.current = false;
    }
  }, [isStreaming, hasContent]);

  useEffect(() => {
    if (!isStreaming && open && !autoCollapsedRef.current && hasContent) {
      const timer = setTimeout(() => {
        setOpen(false);
        autoCollapsedRef.current = true;
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [isStreaming, open, hasContent]);

  // Also expand reasoning when it changes during streaming
  useEffect(() => {
    if (isStreaming && hasReasoning) {
      setReasoningOpen(true);
    }
  }, [isStreaming, hasReasoning]);

  if (!hasContent) return null;

  const summary = buildSummary(toolCalls || [], hasReasoning);
  const pendingCount = (toolCalls || []).filter(
    (t) => t.status === "pending"
  ).length;

  return (
    <div className="mb-2 min-w-0 max-w-full">
      {/* Summary header — always visible when there's content */}
      <button
        type="button"
        className="thinking-summary"
        onClick={() => setOpen(!open)}
      >
        <span
          className={`text-[10px] transition-transform duration-200 ${
            open ? "rotate-90" : ""
          }`}
        >
          ▶
        </span>
        <span>{summary}</span>
        {pendingCount > 0 && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--ninja-accent)] animate-pulse" />
        )}
      </button>

      {/* Expandable body */}
      {open && (
        <div className="mt-2 space-y-2" style={{ animation: "fadeIn 0.2s ease-out" }}>
          {/* Reasoning section */}
          {hasReasoning && (
            <div className="reasoning-section">
              <button
                type="button"
                className="reasoning-toggle"
                onClick={() => setReasoningOpen(!reasoningOpen)}
              >
                <span>{reasoningOpen ? "▾" : "▸"}</span>
                推理过程 ({reasoning!.trim().length}字)
              </button>
              {reasoningOpen && (
                <div className="reasoning-content mt-1.5 pl-3 border-l border-[var(--ninja-accent)]/20">
                  {reasoning}
                </div>
              )}
            </div>
          )}

          {/* Pending indicator */}
          {showPending && !hasToolCalls && !hasReasoning && (
            <div className="flex items-center gap-2 text-xs text-[var(--ninja-text-dim)]">
              <Spinner />
              <span className="animate-pulse-glow">正在分析意图…</span>
            </div>
          )}

          {/* Tool call cards */}
          {hasToolCalls && (
            <div className="space-y-1.5">
              {toolCalls!.map((tc) => (
                <ToolCallCard key={tc.id} tc={tc} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Scoped styles */}
      <style>{`
        .tool-card {
          background: var(--ninja-bg-elevated);
          border: 1px solid var(--ninja-border);
          border-radius: 8px;
          padding: 8px 12px;
          transition: border-color 0.2s;
        }
        .tool-card:hover {
          border-color: var(--ninja-border-strong);
        }
        .tool-card-pending {
          border-left: 2px solid var(--ninja-accent);
        }
        .reasoning-toggle {
          display: flex;
          align-items: center;
          gap: 4px;
          color: var(--ninja-text-dim);
          font-size: 0.75rem;
          cursor: pointer;
          user-select: none;
          background: none;
          border: none;
          padding: 0;
          transition: color 0.15s;
        }
        .reasoning-toggle:hover {
          color: var(--ninja-text-muted);
        }
        .reasoning-content {
          color: var(--ninja-accent);
          opacity: 0.55;
          font-size: 0.75rem;
          white-space: pre-wrap;
          line-height: 1.6;
          max-height: 12rem;
          overflow-y: auto;
        }
        .thinking-summary {
          display: flex;
          align-items: center;
          gap: 6px;
          color: var(--ninja-text-dim);
          font-size: 0.8rem;
          cursor: pointer;
          user-select: none;
          background: none;
          border: none;
          padding: 2px 0;
          transition: color 0.15s;
        }
        .thinking-summary:hover {
          color: var(--ninja-text-muted);
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
