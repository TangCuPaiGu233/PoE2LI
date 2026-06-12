"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ChatMarkdown from "@/components/chat/ChatMarkdown";

// ── types ──
interface TradeMatch { label: string; url: string; count: number }
interface TradeResult { best_match: TradeMatch | null; alternatives: TradeMatch[]; explanation: string }
interface Message { role: "user" | "assistant"; content: string; sources?: { type: string; preview: string }[]; reasoning?: string; trade?: TradeResult }

function apiUrl() {
  if (typeof window === "undefined") return "http://localhost:8000";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

const SKILL_LABELS: Record<string, string> = { encyclopedia: "百科", build_design: "BD 设计", trade_search: "交易搜索" };

const TOOL_LABELS: Record<string, string> = {
  entity_resolve: "解析游戏实体名",
  rag_search: "检索知识库",
  decode_pob: "解析 PoB / 导入 BD",
  trade_search: "搜索交易市场",
  recommend: "对比推荐装备",
};

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
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState("");
  const [skill, setSkill] = useState("idle");
  const [showWelcome, setShowWelcome] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, thinking, reasoning]);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const send = useCallback(async (q: string) => {
    if (!q.trim() || streaming) return;
    setInput(""); setShowWelcome(false);
    const userMsg: Message = { role: "user", content: q };
    const all = [...messages, userMsg];
    setMessages(all); setThinking([]); setReasoning(""); setSkill("idle"); setStreaming(true);

    const history = all.filter(m => m.role === "user" || m.role === "assistant").map(m => ({ role: m.role, content: m.content }));
    let acc = ""; let sk = "idle";

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
              setThinking(p => [...p, t]);
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
              setThinking(p => [...p, argsHint ? `工具调用 · ${label} (${argsHint})` : `工具调用 · ${label}`]);
            } else if (ev.type === "tool_result") {
              const c = ev.content || {};
              const name = typeof c.name === "string" ? c.name : "";
              const label = TOOL_LABELS[name] || name || "工具";
              sk = detectStreamSkill(label, name, sk);
              setSkill(sk);
              const preview = typeof c.preview === "string" ? c.preview : "";
              const prefix = c.ok === false ? "工具失败" : "工具完成";
              setThinking(p => [...p, `${prefix} · ${label}: ${preview}`]);
            } else if (ev.type === "reasoning") setReasoning(p => p + ev.content);
            else if (ev.type === "answer") { acc += ev.content; setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, content: acc }] : [...p, { role: "assistant", content: acc }]; }); }
            else if (ev.type === "trade_result") { setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, trade: ev.content }] : [...p, { role: "assistant", content: "", trade: ev.content }]; }); }
            else if (ev.type === "sources") { setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, content: l.content, sources: ev.content }] : p; }); }
            else if (ev.type === "done") { setReasoning(r => { if (r) setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, reasoning: r }] : p; }); return ""; }); setThinking([]); setStreaming(false); setSkill("idle"); }
          } catch { /* skip malformed */ }
        }
      }
    } catch (e) { setMessages(p => [...p, { role: "assistant", content: `网络错误: ${e}` }]); }
    setStreaming(false); setSkill("idle");
  }, [messages, streaming]);

  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 antialiased">
      <div className="max-w-3xl mx-auto px-4 py-4 flex flex-col h-screen">
        {/* header */}
        <header className="shrink-0 flex items-center justify-between pb-3 border-b border-zinc-800">
          <div className="flex items-baseline gap-3">
            <a href="/" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">首页</a>
            <h1 className="text-sm font-medium text-zinc-200">流放知识库</h1>
          </div>
          <div className="flex items-center gap-2">
            <a href="/trade" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">装备搜索</a>
            {streaming && skill !== "idle" && (
              <span className="text-xs text-amber-500/60 border border-amber-700/30 bg-amber-950/20 rounded-full px-2 py-0.5">
                {SKILL_LABELS[skill] || skill}
              </span>
            )}
          </div>
        </header>

        {/* messages */}
        <main className="flex-1 overflow-y-auto py-6 space-y-8">
          {showWelcome && messages.length === 0 && (
            <div className="pt-12 pb-8">
              <p className="text-xs text-zinc-600 mb-1 tracking-widest uppercase">Ask anything</p>
              <p className="text-2xl text-zinc-200 font-medium mb-8 leading-snug">
                PoE2 知识助手<br />
                <span className="text-zinc-500 text-base font-normal">BD 设计 · 装备搜索 · 机制百科</span>
              </p>
              <div className="flex flex-wrap gap-1.5">
                {CHIPS.map((c, i) => (
                  <button key={i} onClick={() => send(c)} disabled={streaming}
                    className="text-xs px-3 py-1.5 rounded-full border border-zinc-800 text-zinc-500 hover:border-amber-700/40 hover:text-amber-400/80 hover:bg-amber-950/20 transition-all duration-300 disabled:opacity-30">
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
                m.role === "user" ? "bg-zinc-800 text-zinc-400 border border-zinc-700" : "bg-amber-950/30 text-amber-400/80 border border-amber-800/30"
              }`}>
                {m.role === "user" ? "你" : "AI"}
              </div>

              <div className={`min-w-0 max-w-[78%] ${m.role === "user" ? "text-right" : ""}`}>
                {m.reasoning && (
                  <details className="mb-2">
                    <summary className="text-xs text-zinc-500 cursor-pointer hover:text-zinc-400 transition-colors tracking-wider uppercase select-none">思考过程</summary>
                    <div className="mt-2 p-3 bg-zinc-900 border border-zinc-800 rounded-lg text-xs text-zinc-500 leading-relaxed max-h-40 overflow-y-auto whitespace-pre-wrap">{m.reasoning}</div>
                  </details>
                )}

                <div className={`text-sm leading-relaxed rounded-xl px-3.5 py-2.5 ${
                  m.role === "user"
                    ? "bg-amber-950/15 border border-amber-800/20 text-amber-50/80"
                    : "bg-zinc-900/50 border border-zinc-800/40 text-zinc-300"
                }`}>
                  <div className="msg-content"><ChatMarkdown content={m.content} /></div>

                  {m.trade && (
                    <div className="mt-3 pt-3 border-t border-zinc-800">
                      <p className="text-xs text-emerald-500/50 tracking-wider uppercase mb-2">交易结果</p>
                      {m.trade.best_match && (
                        <a href={m.trade.best_match.url} target="_blank" rel="noreferrer"
                          className="block p-2.5 bg-emerald-950/15 border border-emerald-800/25 rounded-lg mb-2 hover:bg-emerald-950/25 transition-colors">
                          <div className="text-xs text-emerald-300/80">{m.trade.best_match.label}</div>
                          <div className="text-xs text-zinc-500 mt-0.5">{m.trade.best_match.count} 件</div>
                        </a>
                      )}
                      {m.trade.alternatives.map((a, j) => (
                        <a key={j} href={a.url} target="_blank" rel="noreferrer"
                          className="block p-2 bg-zinc-900/30 border border-zinc-800 rounded-lg mb-1.5 hover:bg-zinc-900/50 transition-colors">
                          <div className="text-xs text-zinc-400">{a.label}</div>
                          <div className="text-xs text-zinc-600 mt-0.5">{a.count} 件</div>
                        </a>
                      ))}
                    </div>
                  )}

                  {m.sources && m.sources.length > 0 && (
                    <details className="mt-3 pt-2 border-t border-zinc-800">
                      <summary className="text-xs text-zinc-600 cursor-pointer hover:text-zinc-500 transition-colors">来源 ({m.sources.length})</summary>
                      <div className="mt-2 space-y-1">
                        {m.sources.map((s, j) => <div key={j} className="text-xs text-zinc-600 bg-zinc-900/40 rounded px-2 py-1"><span className="text-zinc-500">[{s.type}]</span> {s.preview}</div>)}
                      </div>
                    </details>
                  )}
                </div>
              </div>
            </article>
          ))}

          {reasoning && (
            <article className="flex gap-3">
              <div className="shrink-0 w-8 h-8 rounded-md bg-amber-950/30 border border-amber-800/30 flex items-center justify-center text-xs font-medium text-amber-400/80 mt-0.5">AI</div>
              <details open className="min-w-0 max-w-[78%] rounded-xl px-3.5 py-2.5 bg-zinc-900/50 border border-amber-800/15">
                <summary className="text-xs text-amber-500/50 animate-pulse tracking-wider uppercase cursor-pointer">思考中</summary>
                <div className="mt-2 text-xs text-amber-500/30 whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">{reasoning}</div>
              </details>
            </article>
          )}

          {thinking.length > 0 && (
            <article className="flex gap-3">
              <div className="shrink-0 w-8 h-8 rounded-md bg-zinc-900 border border-zinc-700/50 flex items-center justify-center text-xs font-medium text-zinc-500 mt-0.5">...</div>
              <div className="min-w-0 max-w-[78%] rounded-xl px-3.5 py-2.5 bg-zinc-900/30 border border-zinc-800/30">
                <div className="text-xs text-zinc-600 mb-1.5 tracking-wider uppercase">检索</div>
                {thinking.map((t, i) => <p key={i} className="text-xs text-zinc-600 leading-relaxed">{t}</p>)}
              </div>
            </article>
          )}

          {streaming && !reasoning && thinking.length === 0 && (
            <article className="flex gap-3">
              <div className="shrink-0 w-8 h-8 rounded-md bg-amber-950/30 border border-amber-800/30 flex items-center justify-center text-xs font-medium text-amber-400/80 mt-0.5">AI</div>
              <div className="rounded-xl px-3.5 py-2.5 bg-zinc-900/30 border border-zinc-800/30 flex gap-1 items-center">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500/30 animate-bounce" />
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500/30 animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500/30 animate-bounce [animation-delay:300ms]" />
              </div>
            </article>
          )}

          <div ref={bottomRef} />
        </main>

        {/* input */}
        <footer className="shrink-0 pt-3 border-t border-zinc-800">
          <div className="flex gap-2 items-end">
            <input ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={onKey}
              placeholder={streaming ? "回复中..." : "输入问题，Enter 发送"}
              disabled={streaming}
              className="flex-1 bg-transparent border border-zinc-800 rounded-lg px-3 py-2.5 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-amber-700/40 transition-colors disabled:opacity-40" />
            <button onClick={() => send(input)} disabled={streaming || !input.trim()}
              className="shrink-0 px-4 py-2.5 rounded-lg bg-amber-950/20 border border-amber-800/25 text-amber-400/60 text-sm font-medium hover:bg-amber-950/30 hover:text-amber-300/80 disabled:bg-transparent disabled:border-zinc-800 disabled:text-zinc-700 transition-all duration-200">
              {streaming ? "..." : "发送"}
            </button>
          </div>
        </footer>
      </div>

      <style>{`
        @keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .msg-content .md-p { margin-bottom: 0.5rem; }
        .msg-content .md-p:last-child { margin-bottom: 0; }
        .msg-content .md-h1 { font-size: 1.05rem; font-weight: 600; color: rgba(255,255,255,0.85); margin-top: 1rem; margin-bottom: 0.4rem; line-height: 1.3; }
        .msg-content .md-h2 { font-size: 0.95rem; font-weight: 600; color: rgba(255,255,255,0.8); margin-top: 0.8rem; margin-bottom: 0.3rem; line-height: 1.3; }
        .msg-content .md-h3 { font-size: 0.88rem; font-weight: 600; color: rgba(255,255,255,0.72); margin-top: 0.65rem; margin-bottom: 0.25rem; line-height: 1.3; }
        .msg-content .md-h4 { font-size: 0.82rem; font-weight: 600; color: rgba(255,255,255,0.65); margin-top: 0.5rem; margin-bottom: 0.2rem; line-height: 1.3; }
        .msg-content .md-bold { color: rgba(252,211,77,0.82); font-weight: 500; }
        .msg-content .md-em { font-style: italic; color: rgba(255,255,255,0.55); }
        .msg-content .md-li { display: list-item; margin-left: 1.2rem; list-style: disc; color: rgba(255,255,255,0.5); margin-bottom: 0.15rem; }
        .msg-content .md-li-ol { display: list-item; margin-left: 1.2rem; list-style: decimal; color: rgba(255,255,255,0.5); margin-bottom: 0.15rem; }
        .msg-content .md-code { font-size: 0.82em; background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 3px; color: rgba(252,211,77,0.6); font-family: monospace; }
        .msg-content .md-link { color: rgba(252,211,77,0.7); text-decoration: underline; }
        .msg-content .md-link:hover { color: rgba(252,211,77,0.9); }
        .msg-content .md-quote { border-left: 2px solid rgba(252,211,77,0.3); padding-left: 0.75rem; margin: 0.5rem 0; color: rgba(255,255,255,0.45); font-style: italic; }
        .msg-content .md-hr { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 0.6rem 0; }
        .msg-content .md-tag { font-size: 0.65rem; color: rgba(255,255,255,0.22); background: rgba(255,255,255,0.03); padding: 0 2px; border-radius: 2px; margin: 0 1px; }
        .msg-content .md-tag-guess { color: rgba(252,211,77,0.32); background: rgba(252,211,77,0.04); }

        .msg-content .md-table-wrap { overflow-x: auto; margin: 0.65rem 0; border: 1px solid rgba(255,255,255,0.08); border-radius: 0.5rem; }
        .msg-content .md-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
        .msg-content .md-thead { background: rgba(255,255,255,0.04); }
        .msg-content .md-th, .msg-content .md-td { padding: 0.45rem 0.65rem; border-bottom: 1px solid rgba(255,255,255,0.06); text-align: left; vertical-align: top; }
        .msg-content .md-th { color: rgba(252,211,77,0.75); font-weight: 600; }
        .msg-content .md-td { color: rgba(255,255,255,0.55); }
        .msg-content .md-tr:last-child .md-td { border-bottom: none; }
      `}</style>
    </div>
  );
}
