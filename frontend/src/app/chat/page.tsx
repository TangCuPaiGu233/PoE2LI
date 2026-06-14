"use client";

import { apiUrl } from "@/lib/apiUrl";
import { useState, useRef, useEffect, useCallback } from "react";
import ChatMarkdown from "@/components/chat/ChatMarkdown";

// ── types ──
interface TradeMatch { label: string; url: string; count: number }
interface TradeResult { best_match: TradeMatch | null; alternatives: TradeMatch[]; explanation: string }
interface Message { role: "user" | "assistant"; content: string; sources?: { type: string; preview: string }[]; reasoning?: string; thinkingSteps?: string[]; trade?: TradeResult; trades?: TradeResult[]; followUps?: string[] }

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
  defaultOpen,
}: {
  steps?: string[];
  reasoning?: string;
  defaultOpen?: boolean;
}) {
  const hasSteps = !!(steps && steps.length);
  const hasReasoning = !!reasoning?.trim();
  if (!hasSteps && !hasReasoning) {
    if (!defaultOpen) return null;
    return (
      <details className="mt-2 min-w-0 max-w-full" open={defaultOpen}>
        <summary className="text-xs text-[var(--ninja-text-dim)] cursor-pointer hover:text-[var(--ninja-text-muted)] transition-colors tracking-wider uppercase select-none">
          思考过程
        </summary>
        <div className="mt-2 p-3 ninja-panel text-xs leading-relaxed max-h-48 overflow-y-auto">
          <p className="text-[var(--ninja-text-dim)] animate-pulse-glow">正在分析意图...</p>
        </div>
      </details>
    );
  }
  return (
    <details className="mt-2 min-w-0 max-w-full" open={defaultOpen}>
      <summary className="text-xs text-[var(--ninja-text-dim)] cursor-pointer hover:text-[var(--ninja-text-muted)] transition-colors tracking-wider uppercase select-none">
        思考过程
      </summary>
      <div className="mt-2 p-3 ninja-panel text-xs text-[var(--ninja-text-muted)] leading-relaxed max-h-48 overflow-y-auto space-y-1.5">
        {hasSteps && steps!.map((t, i) => (
          <p key={`step-${i}`} className="text-[var(--ninja-text-muted)]">{t}</p>
        ))}
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
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState("");
  const [skill, setSkill] = useState("idle");
  const [showWelcome, setShowWelcome] = useState(true);
  const mainRef = useRef<HTMLElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
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

  const send = useCallback(async (q: string) => {
    if (!q.trim() || streaming) return;
    setInput(""); setShowWelcome(false);
    stickToBottomRef.current = true;
    const userMsg: Message = { role: "user", content: q };
    const all = [...messages, userMsg];
    setMessages(all); setThinking(["已收到问题，正在连接服务器…"]); setReasoning(""); setSkill("idle"); setStreaming(true);

    const history = all.filter(m => m.role === "user" || m.role === "assistant").map(m => ({ role: m.role, content: m.content }));
    let acc = ""; let sk = "idle"; let pendingFollowUps: string[] | null = null;
    let thinkLog: string[] = ["已收到问题，正在连接服务器…"];
    let reasonLog = "";

    try {
      const resp = await fetch(`${apiUrl()}/api/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: history, stream: true }) });
      const reader = resp.body?.getReader();
      if (!reader) { setMessages(p => [...p, { role: "assistant", content: "无响应" }]); setStreaming(false); return; }

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
            else if (ev.type === "trade_result") { setMessages(p => { const l = p[p.length - 1]; if (l?.role === "assistant") { const trades = [...(l.trades || (l.trade ? [l.trade] : [])), ev.content as TradeResult]; return [...p.slice(0, -1), { ...l, trades, trade: undefined }]; } return [...p, { role: "assistant", content: "", trades: [ev.content as TradeResult] }]; }); }
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
    } catch (e) { setMessages(p => [...p, { role: "assistant", content: `网络错误: ${e}` }]); }
    setStreaming(false); setSkill("idle");
  }, [messages, streaming]);

  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } };

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

              <div className={`min-w-0 max-w-[78%] ${m.role === "user" ? "text-right" : ""}`}>
                                <div className={`text-base leading-7 rounded-xl px-4 py-3 ${
                  m.role === "user"
                    ? "bg-[rgba(30,203,139,0.08)] border border-[rgba(30,203,139,0.2)] text-[var(--ninja-text)]"
                    : "ninja-panel text-[var(--ninja-text-body)]"
                }`}>
                  <div className="msg-content">
                  {m.role === "user" ? (
                    <p className="md-p whitespace-pre-wrap">{m.content}</p>
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
                            <a href={tr.best_match.url} target="_blank" rel="noreferrer"
                              className="block p-2.5 ninja-panel-accent mb-1 hover:bg-[var(--ninja-panel-hover)] transition-colors">
                              <div className="text-xs text-[var(--ninja-accent)]">{tr.best_match.label}</div>
                              <div className="text-xs text-[var(--ninja-text-dim)] mt-0.5">{tr.best_match.count} 件</div>
                            </a>
                          )}
                          {tr.alternatives.map((a, j) => (
                            <a key={j} href={a.url} target="_blank" rel="noreferrer"
                              className="block p-2 ninja-panel mb-1 hover:bg-[var(--ninja-panel-hover)] transition-colors">
                              <div className="text-xs text-[var(--ninja-text-muted)]">{a.label}</div>
                              <div className="text-xs text-[var(--ninja-text-dim)] mt-0.5">{a.count} 件</div>
                            </a>
                          ))}
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
                {m.role === "assistant" && (() => {
                  const isLast = i === messages.length - 1;
                  const liveStream = streaming && isLast;
                  if (liveStream) {
                    return (
                      <ThinkingPanel steps={thinking} reasoning={reasoning} defaultOpen />
                    );
                  }
                  return (
                    <ThinkingPanel steps={m.thinkingSteps} reasoning={m.reasoning} />
                  );
                })()}
              </div>
            </article>
          ))}

          {streaming && messages[messages.length - 1]?.role !== "assistant" && (
            <article className="flex gap-3">
              <div className="shrink-0 w-8 h-8 rounded-md bg-[rgba(30,203,139,0.12)] border border-[rgba(30,203,139,0.3)] flex items-center justify-center text-xs font-medium text-[var(--ninja-accent)] mt-0.5">
                AI
              </div>
              <div className="min-w-0 max-w-[78%]">
                <ThinkingPanel steps={thinking} reasoning={reasoning} defaultOpen />
              </div>
            </article>
          )}

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

        {/* input */}
        <footer className="shrink-0 pt-3 border-t border-[var(--ninja-border)]">
          <div className="flex gap-2 items-end">
            <input ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={onKey}
              placeholder={streaming ? "回复中..." : "输入问题，Enter 发送"}
              disabled={streaming}
              className="ninja-input flex-1 disabled:opacity-40" />
            <button onClick={() => send(input)} disabled={streaming || !input.trim()}
              className="ninja-btn shrink-0 px-4 py-2.5 disabled:opacity-40">
              {streaming ? "..." : "发送"}
            </button>
          </div>
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
