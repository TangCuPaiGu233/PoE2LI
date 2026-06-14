"use client";

import { apiUrl } from "@/lib/apiUrl";
import {
  createPendingPlaceholders,
  extractImageFilesFromDataTransfer,
  MAX_IMAGES,
  resolvePlaceholderImages,
  type PendingImage,
} from "@/lib/chatImage";
import { useState, useRef, useEffect, useCallback } from "react";
import ChatMarkdown from "@/components/chat/ChatMarkdown";
import ChatMessageImage from "@/components/chat/ChatMessageImage";

// ── types ──
interface TradeMatch {
  label: string;
  url: string;
  count: number;
  degraded?: boolean;
  empty?: boolean;
  broad?: boolean;
}
interface TradeResult {
  best_match: TradeMatch | null;
  alternatives: TradeMatch[];
  explanation: string;
  degraded?: boolean;
  listing_price?: { display?: string; amount?: number; currency?: string; item_name?: string };
  price_note?: string;
}

function tradeCountBadge(m: TradeMatch): string {
  if (m.empty || m.count === 0) return "无在售 · 可查看筛选";
  if (m.broad || m.count >= 5000) return `${m.count}+ 件 · 条件较宽`;
  return `${m.count} 件在售`;
}

function TradeMatchCard({
  match,
  primary,
  listingPrice,
}: {
  match: TradeMatch;
  primary?: boolean;
  listingPrice?: TradeResult["listing_price"];
}) {
  return (
    <a
      href={match.url}
      target="_blank"
      rel="noreferrer"
      className={
        primary
          ? "block p-2.5 ninja-panel-accent mb-1 hover:bg-[var(--ninja-panel-hover)] transition-colors"
          : "block p-2 ninja-panel mb-1 hover:bg-[var(--ninja-panel-hover)] transition-colors"
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs text-[var(--ninja-accent)] min-w-0">{match.label}</div>
        <span
          className={
            match.empty
              ? "shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-[var(--ninja-bg-elevated)] text-[var(--ninja-text-dim)]"
              : "shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-[var(--ninja-bg-elevated)] text-[var(--ninja-text-muted)]"
          }
        >
          {tradeCountBadge(match)}
        </span>
      </div>
      {primary && listingPrice?.display && (
        <div className="text-xs text-[var(--ninja-text-dim)] mt-1">
          市集参考价 {listingPrice.display}
          {listingPrice.item_name ? ` · ${listingPrice.item_name}` : ""}
        </div>
      )}
    </a>
  );
}
interface Message {
  role: "user" | "assistant";
  content: string;
  images?: string[];
  sources?: { type: string; preview: string }[];
  reasoning?: string;
  thinkingSteps?: string[];
  trade?: TradeResult;
  trades?: TradeResult[];
  followUps?: string[];
}

const SKILL_LABELS: Record<string, string> = { encyclopedia: "百科", build_design: "BD 设计", trade_search: "交易搜索" };

const TOOL_LABELS: Record<string, string> = {
  entity_resolve: "解析游戏实体名",
  rag_search: "检索知识库",
  decode_pob: "解析 PoB / 导入 BD",
  trade_search: "搜索交易市场",
  recommend: "对比推荐装备",
};



function ThinkingPanel({
  steps,
  reasoning,
  showPending,
}: {
  steps?: string[];
  reasoning?: string;
  showPending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const hasSteps = !!(steps && steps.length);
  const hasReasoning = !!reasoning?.trim();
  if (!hasSteps && !hasReasoning && !showPending) return null;
  return (
    <details
      className="mb-2 min-w-0 max-w-full"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary className="text-xs text-[var(--ninja-text-dim)] cursor-pointer hover:text-[var(--ninja-text-muted)] transition-colors tracking-wider uppercase select-none">
        思考过程
      </summary>
      <div className="mt-2 p-3 ninja-panel text-xs text-[var(--ninja-text-muted)] leading-relaxed max-h-48 overflow-y-auto space-y-1.5">
        {hasSteps && steps!.map((t, i) => (
          <p key={`step-${i}`} className="text-[var(--ninja-text-muted)]">{t}</p>
        ))}
        {!hasSteps && showPending && (
          <p className="text-[var(--ninja-text-dim)] animate-pulse-glow">正在分析意图...</p>
        )}
        {hasReasoning && (
          <p className="text-[var(--ninja-accent)] opacity-60 whitespace-pre-wrap">{reasoning}</p>
        )}
      </div>
    </details>
  );
}

function detectStreamSkill(text: string, toolName?: string, current = "idle"): string {
  if (toolName === "trade_search" || text.includes("交易市场")) return "trade_search";
  if (
    toolName === "decode_pob" ||
    /PoB|pobb\.in|decode_pob|decode/i.test(text) ||
    text.includes("导入 BD") ||
    text.includes("解析 PoB")
  )
    return "build_design";
  if (toolName === "rag_search" || text.includes("检索") || text.includes("知识库")) return "encyclopedia";
  if (text.includes("分析")) return "encyclopedia";
  return current;
}

const CHIPS = [
  "帮我配一个召唤女巫的开荒BD",
  "帮我找一条加2召唤技能等级的项链",
  "灵魂行者有哪些升华技能",
  "扭曲项链都能提供什么词条",
  "粘贴 poe.ninja 角色链接，估算BD造价",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [imageError, setImageError] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const [isComposing, setIsComposing] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState("");
  const [skill, setSkill] = useState("idle");
  const [showWelcome, setShowWelcome] = useState(true);
  const mainRef = useRef<HTMLElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottomRef = useRef(true);

  const SCROLL_THRESHOLD = 72;

  const updateStickToBottom = useCallback(() => {
    const el = mainRef.current;
    if (!el) return;
    stickToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_THRESHOLD;
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    if (!stickToBottomRef.current) return;
    bottomRef.current?.scrollIntoView({ behavior });
  }, []);

  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateStickToBottom, { passive: true });
    return () => el.removeEventListener("scroll", updateStickToBottom);
  }, [updateStickToBottom]);

  useEffect(() => {
    scrollToBottom(streaming ? "auto" : "smooth");
  }, [messages, thinking, reasoning, streaming, scrollToBottom]);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const send = useCallback(async (q: string, imageDataUrls?: string[]) => {
    const text = q.trim();
    const imgs = imageDataUrls?.length ? imageDataUrls : [];
    if ((!text && !imgs.length) || streaming) return;
    setInput(""); setPendingImages([]); setImageError(""); setShowWelcome(false);
    stickToBottomRef.current = true;
    const userMsg: Message = { role: "user", content: text, ...(imgs.length ? { images: imgs } : {}) };
    const assistantDraft: Message = { role: "assistant", content: "" };
    const all = [...messages, userMsg, assistantDraft];
    setMessages(all); setThinking(["已收到问题，正在连接服务器…"]); setReasoning(""); setSkill("idle"); setStreaming(true);

    type ApiMsg = { role: string; content: string; images?: string[] };
    const history: ApiMsg[] = [...messages, userMsg]
      .filter(m => m.role === "user" || (m.role === "assistant" && m.content.trim()))
      .map(m => ({
        role: m.role,
        content: m.content,
        ...(m.images?.length ? { images: m.images } : {}),
      }));
    let acc = ""; let sk = "idle"; let pendingFollowUps: string[] | null = null;
    let thinkLog: string[] = ["已收到问题，正在连接服务器…"];
    let reasonLog = "";

    try {
      const resp = await fetch(`${apiUrl()}/api/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: history, stream: true }) });
      const reader = resp.body?.getReader();
      if (!reader) {
        setMessages(p => {
          const l = p[p.length - 1];
          return l?.role === "assistant"
            ? [...p.slice(0, -1), { ...l, content: "无响应" }]
            : [...p, { role: "assistant", content: "无响应" }];
        });
        setStreaming(false);
        return;
      }

      const dec = new TextDecoder(); let buf = "";
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "thinking") {
              const t = ev.content || "";
              sk = detectStreamSkill(t, undefined, sk);
              setSkill(sk);
              thinkLog.push(t);
              setThinking([...thinkLog]);
            } else if (ev.type === "tool_use") {
              const c = ev.content || {};
              const name = typeof c.name === "string" ? c.name : "";
              const label = TOOL_LABELS[name] || name || "工具调用";
              sk = detectStreamSkill(label, name, sk);
              setSkill(sk);
              const args = c.arguments;
              let argsHint = "";
              if (args && typeof args === "object") {
                argsHint = Object.entries(args as Record<string, unknown>)
                  .slice(0, 2)
                  .map(([k, v]) => `${k}: ${String(v).slice(0, 60)}`)
                  .join(", ");
              }
              const toolLine = argsHint ? `工具调用 · ${label} (${argsHint})` : `工具调用 · ${label}`;
              thinkLog.push(toolLine);
              setThinking([...thinkLog]);
            } else if (ev.type === "tool_result") {
              const c = ev.content || {};
              const name = typeof c.name === "string" ? c.name : "";
              const label = TOOL_LABELS[name] || name || "工具";
              sk = detectStreamSkill(label, name, sk);
              setSkill(sk);
              const preview = typeof c.preview === "string" ? c.preview : "";
              const prefix = c.ok === false ? "工具失败" : "工具完成";
              thinkLog.push(`${prefix} · ${label}: ${preview}`);
              setThinking([...thinkLog]);
            } else if (ev.type === "reasoning") { reasonLog += ev.content; setReasoning(reasonLog); }
            else if (ev.type === "answer") { acc += ev.content; setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, content: acc }] : [...p, { role: "assistant", content: acc }]; }); }
            else if (ev.type === "trade_result") { setMessages(p => { const l = p[p.length - 1]; if (l?.role === "assistant") { return [...p.slice(0, -1), { ...l, trades: [ev.content as TradeResult], trade: undefined }]; } return [...p, { role: "assistant", content: "", trades: [ev.content as TradeResult] }]; }); }
            else if (ev.type === "sources") { setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, content: l.content, sources: ev.content }] : p; }); }
            else if (ev.type === "follow_ups") { const qs = Array.isArray(ev.content) ? ev.content.filter((q: unknown) => typeof q === "string" && q.trim()) : []; if (qs.length) pendingFollowUps = qs.slice(0, 3); }
            else if (ev.type === "done") {
              const fu = pendingFollowUps?.length ? pendingFollowUps.slice(0, 3) : null;
              pendingFollowUps = null;
              const savedSteps = thinkLog.length ? [...thinkLog] : undefined;
              const savedReasoning = reasonLog || undefined;
              setMessages(p => {
                const l = p[p.length - 1];
                if (l?.role !== "assistant") return p;
                return [...p.slice(0, -1), {
                  ...l,
                  ...(savedReasoning ? { reasoning: savedReasoning } : {}),
                  ...(savedSteps ? { thinkingSteps: savedSteps } : {}),
                  ...(fu ? { followUps: fu } : {}),
                }];
              });
              thinkLog = [];
              reasonLog = "";
              setThinking([]);
              setReasoning("");
              setStreaming(false);
              setSkill("idle");
            }
          } catch { /* skip malformed */ }
        }
      }
    } catch (e) {
      setMessages(p => {
        const l = p[p.length - 1];
        return l?.role === "assistant"
          ? [...p.slice(0, -1), { ...l, content: `网络错误: ${e}` }]
          : [...p, { role: "assistant", content: `网络错误: ${e}` }];
      });
    }
    setStreaming(false); setSkill("idle");
  }, [messages, streaming]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !isComposing) {
      e.preventDefault();
      send(input, pendingImages.filter(p => p.dataUrl && !p.isLoading).map(p => p.dataUrl));
    }
  };

  const addImagesFromFiles = useCallback(async (files: File[]) => {
    if (!files.length || streaming) return;
    setImageError("");
    const room = MAX_IMAGES - pendingImages.length;
    if (room <= 0) {
      setImageError(`最多 ${MAX_IMAGES} 张图片`);
      return;
    }
    const batch = files.slice(0, room);
    if (files.length > room) {
      setImageError(`最多 ${MAX_IMAGES} 张，已添加 ${room} 张`);
    }
    const placeholders = createPendingPlaceholders(batch.length);
    const ids = placeholders.map(p => p.id);
    setPendingImages(p => [...p, ...placeholders]);
    const resolved = await resolvePlaceholderImages(placeholders, batch);
    setPendingImages(p => {
      const next = [...p];
      for (let i = 0; i < ids.length; i++) {
        const idx = next.findIndex(x => x.id === ids[i]);
        if (idx >= 0) next[idx] = resolved[i];
      }
      return next;
    });
  }, [pendingImages.length, streaming]);

  useEffect(() => {
    const onWindowPaste = (e: ClipboardEvent) => {
      if (streaming) return;
      const imageFiles = extractImageFilesFromDataTransfer(e.clipboardData);
      if (!imageFiles.length) return;
      const active = document.activeElement;
      if (
        active instanceof HTMLInputElement ||
        (active instanceof HTMLElement && active.isContentEditable && active !== inputRef.current)
      ) {
        return;
      }
      e.preventDefault();
      inputRef.current?.focus();
      void addImagesFromFiles(imageFiles);
    };
    window.addEventListener("paste", onWindowPaste);
    return () => window.removeEventListener("paste", onWindowPaste);
  }, [addImagesFromFiles, streaming]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const imageFiles = extractImageFilesFromDataTransfer(e.dataTransfer);
    if (imageFiles.length) void addImagesFromFiles(imageFiles);
  }, [addImagesFromFiles]);

  const onDragOver = useCallback((e: React.DragEvent) => {
    const hasImage = extractImageFilesFromDataTransfer(e.dataTransfer).length > 0;
    if (!hasImage) return;
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const readyImages = pendingImages.filter(p => p.dataUrl && !p.isLoading && !p.error);
  const canSend = !streaming && (input.trim().length > 0 || readyImages.length > 0) && !pendingImages.some(p => p.isLoading);

  return (
    <div className="text-[var(--ninja-text)] antialiased">
      <div className="max-w-4xl mx-auto px-4 py-4 flex flex-col min-h-[calc(100vh-3rem)]">
        {/* header */}
        <header className="shrink-0 flex items-center justify-between pb-3 border-b border-[var(--ninja-border)]">
          <div className="flex items-baseline gap-3">
            <a href="/" className="text-xs text-[var(--ninja-text-muted)] hover:text-[var(--ninja-text)] transition-colors">首页</a>
            <h1 className="text-sm font-medium text-[var(--ninja-text)]">流放知识库</h1>
          </div>
          <div className="flex items-center gap-2">
            {streaming && skill !== "idle" && (
              <span className="ninja-badge border-[rgba(30,203,139,0.35)] text-[var(--ninja-accent)] bg-[rgba(30,203,139,0.08)]">
                {SKILL_LABELS[skill] || skill}
              </span>
            )}
          </div>
        </header>

        {/* messages */}
        <main ref={mainRef} className="flex-1 overflow-y-auto py-6 space-y-8">
          {showWelcome && messages.length === 0 && (
            <div className="pt-12 pb-8">
              <p className="ninja-section-title mb-1">Ask anything</p>
              <p className="text-2xl text-[var(--ninja-text)] font-semibold mb-2 leading-snug">
                PoE2 知识助手<br />
                <span className="text-[var(--ninja-text-muted)] text-base font-normal">BD 设计 · 装备搜索 · 机制百科</span>
              </p>
              <div className="flex flex-wrap gap-1.5">
                {CHIPS.map((c, i) => (
                  <button key={i} onClick={() => send(c)} disabled={streaming}
                    className="ninja-chip disabled:opacity-30">
                    {c}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <article key={i} className={`flex gap-3 ${m.role === "user" ? "flex-row-reverse" : ""}`}
              style={{ animation: `msgIn 0.3s ease-out ${i * 0.02}s both` }}>
              <div className={`shrink-0 w-8 h-8 rounded-md flex items-center justify-center text-xs font-medium mt-0.5 ${
                m.role === "user" ? "bg-[var(--ninja-bg-elevated)] text-[var(--ninja-text-muted)] border border-[var(--ninja-border)]" : "bg-[rgba(30,203,139,0.12)] text-[var(--ninja-accent)] border border-[rgba(30,203,139,0.3)]"
              }`}>
                {m.role === "user" ? "你" : "AI"}
              </div>

              <div className={`min-w-0 max-w-[78%] flex flex-col ${m.role === "user" ? "text-right" : ""}`}>
                {m.role === "assistant" && (() => {
                  const isLast = i === messages.length - 1;
                  const liveStream = streaming && isLast;
                  return (
                    <ThinkingPanel
                      steps={liveStream ? thinking : m.thinkingSteps}
                      reasoning={liveStream ? reasoning : m.reasoning}
                      showPending={liveStream && thinking.length === 0 && !reasoning}
                    />
                  );
                })()}
                {(m.role === "user" || m.content.trim() || (m.images && m.images.length > 0) || (m.trades?.length ? m.trades : m.trade ? [m.trade] : []).length > 0 || (m.sources && m.sources.length > 0)) && (
                <div className={`text-base leading-7 rounded-xl px-4 py-3 ${
                  m.role === "user"
                    ? "bg-[rgba(30,203,139,0.08)] border border-[rgba(30,203,139,0.2)] text-[var(--ninja-text)]"
                    : "ninja-panel text-[var(--ninja-text-body)]"
                }`}>
                  <div className="msg-content">
                  {m.role === "user" ? (
                    <>
                      {m.images && m.images.length > 0 && (
                        <div className={`flex flex-wrap gap-2 mb-2 ${m.role === "user" ? "justify-end" : ""}`}>
                          {m.images.map((src, j) => (
                            <ChatMessageImage
                              key={j}
                              src={src}
                              alt={`附件 ${j + 1}`}
                              fileName={`chat-${i + 1}-${j + 1}.jpg`}
                              className="max-h-40 max-w-full rounded-lg border border-[rgba(30,203,139,0.25)] object-contain"
                            />
                          ))}
                        </div>
                      )}
                      {m.content.trim() ? (
                        <p className="md-p whitespace-pre-wrap">{m.content}</p>
                      ) : null}
                    </>
                  ) : (
                    <ChatMarkdown content={m.content} enableEntityChips />
                  )}
                </div>

                  {(m.trades?.length ? m.trades : m.trade ? [m.trade] : []).length > 0 && (
                    <div className="mt-3 pt-3 border-t border-[var(--ninja-border)]">
                      <p className="ninja-section-title mb-2">交易结果</p>
                      {(m.trades?.length ? m.trades : m.trade ? [m.trade] : []).map((tr, ti) => (
                        <div key={ti} className="mb-2">
                          {tr.best_match && (
                            <TradeMatchCard
                              match={tr.best_match}
                              primary
                              listingPrice={tr.listing_price}
                            />
                          )}
                          {tr.alternatives.map((a, j) => (
                            <TradeMatchCard key={j} match={a} />
                          ))}
                          {tr.price_note && tr.best_match?.empty && (
                            <p className="text-[10px] text-[var(--ninja-text-dim)] mt-1 px-0.5">
                              {tr.price_note}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {m.sources && m.sources.length > 0 && (
                    <details className="mt-3 pt-2 border-t border-[var(--ninja-border)]">
                      <summary className="text-xs text-[var(--ninja-text-dim)] cursor-pointer hover:text-[var(--ninja-text-muted)] transition-colors">来源 ({m.sources.length})</summary>
                      <div className="mt-2 space-y-1">
                        {m.sources.map((s, j) => <div key={j} className="text-xs text-[var(--ninja-text-dim)] bg-[var(--ninja-bg-elevated)] rounded px-2 py-1"><span className="text-[var(--ninja-text-muted)]">[{s.type}]</span> {s.preview}</div>)}
                      </div>
                    </details>
                  )}
                </div>
                )}
              </div>
            </article>
          ))}


          <div ref={bottomRef} />
        </main>

        {/* follow-up suggestions */}
        {!streaming && messages.length > 0 && messages[messages.length - 1]?.role === "assistant" && (messages[messages.length - 1]?.followUps?.length ?? 0) > 0 && (
          <div className="shrink-0 pb-3 border-b border-[var(--ninja-border)]">
            <p className="ninja-section-title mb-2">你可能还想问</p>
            <div className="flex flex-col gap-1.5">
              {messages[messages.length - 1].followUps!.map((q, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => { setInput(q); inputRef.current?.focus(); }}
                  className="ninja-follow-chip whitespace-normal"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* input — paste / drag-drop images (goose ChatInput pattern) */}
        <footer className="shrink-0 pt-3 border-t border-[var(--ninja-border)]">
          <div
            className={`rounded-xl border transition-colors ${
              isDragOver
                ? "border-[rgba(30,203,139,0.55)] bg-[rgba(30,203,139,0.06)]"
                : "border-[var(--ninja-border)] bg-[var(--ninja-bg-elevated)]/40"
            }`}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragLeave={() => setIsDragOver(false)}
          >
            {pendingImages.length > 0 && (
              <div className="flex flex-wrap gap-2 p-2 pb-0">
                {pendingImages.map(img => (
                  <div key={img.id} className="relative">
                    {img.isLoading ? (
                      <div className="h-16 w-16 rounded-md border border-[var(--ninja-border)] bg-[var(--ninja-bg-elevated)] animate-pulse" />
                    ) : img.error ? (
                      <div className="h-16 w-24 rounded-md border border-red-500/40 px-1 text-[10px] text-red-400 flex items-center justify-center text-center">
                        {img.error}
                      </div>
                    ) : (
                      <ChatMessageImage
                        src={img.dataUrl}
                        alt={img.name || "附件"}
                        fileName={img.name || "pasted-image.jpg"}
                        thumb
                        className="h-16 w-16 object-cover rounded-md border border-[var(--ninja-border)]"
                      />
                    )}
                    {!img.isLoading && (
                      <button
                        type="button"
                        aria-label="移除图片"
                        onClick={() => setPendingImages(p => p.filter(x => x.id !== img.id))}
                        className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-[var(--ninja-bg-elevated)] border border-[var(--ninja-border)] text-[10px] text-[var(--ninja-text-muted)] hover:text-[var(--ninja-text)]"
                      >
                        ×
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            {imageError && (
              <p className="text-xs text-red-400/90 px-3 pt-2">{imageError}</p>
            )}
            <div className="flex gap-2 items-end p-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={onKey}
                onCompositionStart={() => setIsComposing(true)}
                onCompositionEnd={() => setIsComposing(false)}
                rows={1}
                placeholder={streaming ? "回复中..." : "输入问题；可直接 Ctrl+V 粘贴截图，或拖入图片"}
                disabled={streaming}
                className="ninja-input flex-1 min-h-[2.75rem] max-h-40 resize-y disabled:opacity-40 bg-transparent border-0 focus:ring-0"
              />
              <button
                type="button"
                onClick={() => send(input, readyImages.map(p => p.dataUrl))}
                disabled={!canSend}
                className="ninja-btn shrink-0 px-4 py-2.5 disabled:opacity-40"
              >
                {streaming ? "..." : "发送"}
              </button>
            </div>
          </div>
          <p className="text-[10px] text-[var(--ninja-text-dim)] mt-1.5 px-1">
            Enter 发送 · Shift+Enter 换行 · 支持截图粘贴与拖放（最多 {MAX_IMAGES} 张）
          </p>
        </footer>
      </div>

      <style>{`
        @keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .msg-content { font-size: 1rem; line-height: 1.75; color: var(--ninja-text-body); }
        .msg-content .md-p { margin-bottom: 0.65rem; color: var(--ninja-text-body); }
        .msg-content .md-p:last-child { margin-bottom: 0; }
        .msg-content .md-h1 { font-size: 1.2rem; font-weight: 600; color: var(--ninja-text); margin-top: 1rem; margin-bottom: 0.45rem; line-height: 1.4; }
        .msg-content .md-h2 { font-size: 1.1rem; font-weight: 600; color: var(--ninja-text); margin-top: 0.85rem; margin-bottom: 0.35rem; line-height: 1.4; }
        .msg-content .md-h3 { font-size: 1.02rem; font-weight: 600; color: var(--ninja-text); margin-top: 0.7rem; margin-bottom: 0.3rem; line-height: 1.4; }
        .msg-content .md-h4 { font-size: 0.98rem; font-weight: 600; color: var(--ninja-text); margin-top: 0.55rem; margin-bottom: 0.25rem; line-height: 1.4; }
        .msg-content .md-bold { color: #3eeaa8; font-weight: 600; }
        .msg-content .md-em { font-style: italic; color: var(--ninja-text-muted); }
        .msg-content .md-li { display: list-item; margin-left: 1.35rem; list-style: disc; color: var(--ninja-text-body); margin-bottom: 0.35rem; line-height: 1.7; }
        .msg-content .md-li-ol { display: list-item; margin-left: 1.35rem; list-style: decimal; color: var(--ninja-text-body); margin-bottom: 0.35rem; line-height: 1.7; }
        .msg-content .md-code { font-size: 0.9em; background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 4px; color: #5dffc0; font-family: ui-monospace, monospace; }
        .msg-content .md-link { color: #3eeaa8; text-decoration: underline; text-underline-offset: 2px; }
        .msg-content .md-link:hover { color: #6ff0c4; }
        .msg-content .md-quote { border-left: 3px solid rgba(30,203,139,0.4); padding-left: 0.85rem; margin: 0.65rem 0; color: var(--ninja-text-muted); font-style: italic; }
        .msg-content .md-hr { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 0.6rem 0; }
        .msg-content .md-tag { font-size: 0.65rem; color: rgba(255,255,255,0.22); background: rgba(255,255,255,0.03); padding: 0 2px; border-radius: 2px; margin: 0 1px; }
        .msg-content .md-tag-guess { color: rgba(30,203,139,0.32); background: rgba(30,203,139,0.04); }

        .msg-content .md-table-wrap { overflow-x: auto; margin: 0.65rem 0; border: 1px solid rgba(255,255,255,0.08); border-radius: 0.5rem; }
        .msg-content .md-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        .msg-content .md-thead { background: rgba(255,255,255,0.04); }
        .msg-content .md-th, .msg-content .md-td { padding: 0.45rem 0.65rem; border-bottom: 1px solid rgba(255,255,255,0.06); text-align: left; vertical-align: top; }
        .msg-content .md-th { color: rgba(30,203,139,0.75); font-weight: 600; }
        .msg-content .md-td { color: var(--ninja-text-body); }
        .msg-content .md-tr:last-child .md-td { border-bottom: none; }
      `}</style>
    </div>
  );
}
