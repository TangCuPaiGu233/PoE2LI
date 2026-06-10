"use client";

import { useState, useRef, useEffect, useCallback } from "react";

// ── types ──
interface TradeMatch { label: string; url: string; count: number }
interface TradeResult { best_match: TradeMatch | null; alternatives: TradeMatch[]; explanation: string }
interface Message { role: "user" | "assistant"; content: string; sources?: { type: string; preview: string }[]; reasoning?: string; trade?: TradeResult }

function apiUrl() {
  if (typeof window === "undefined") return "http://localhost:8000";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

// ── skill badge ──
const SKILL_LABELS: Record<string, string> = { encyclopedia: "百科", build_design: "BD 设计", trade_search: "交易搜索" };
const SKILL_COLORS: Record<string, string> = { encyclopedia: "text-cyan-400 border-cyan-700/40 bg-cyan-950/30", build_design: "text-amber-400 border-amber-700/40 bg-amber-950/30", trade_search: "text-emerald-400 border-emerald-700/40 bg-emerald-950/30" };

// ── suggested queries ──
const QUERY_CHIPS = [
  { q: "帮我配一个召唤女巫的开荒BD" },
  { q: "帮我找一条加2召唤技能等级的项链" },
  { q: "灵魂行者有哪些升华技能" },
  { q: "扭曲项链都能提供什么词条" },
];

// ── markdown-ish renderer (simple, safe) ──
function renderContent(text: string): string {
  let h = text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  h = h.replace(/^### (.+)$/gm, '<h3 class="t-h3">$1</h3>');
  h = h.replace(/^## (.+)$/gm, '<h2 class="t-h2">$1</h2>');
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong class="t-bold">$1</strong>');
  h = h.replace(/^- (.+)$/gm, '<li class="t-li">$1</li>');
  h = h.replace(/`([^`]+)`/g, '<code class="t-code">$1</code>');
  h = h.replace(/\[资料\]/g, '<span class="t-tag">资料</span>');
  h = h.replace(/\[推测\]/g, '<span class="t-tag t-tag-guess">推测</span>');
  return h;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState("");
  const [skill, setSkill] = useState("idle");
  const [empty, setEmpty] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, thinking, reasoning]);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const send = useCallback(async (q: string) => {
    if (!q.trim() || streaming) return;
    setInput(""); setEmpty(false);
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
            if (ev.type === "thinking") { const t = ev.content || ""; if (t.includes("交易市场")) sk = "trade_search"; else if (t.includes("分析")) sk = "encyclopedia"; setSkill(sk); setThinking(p => [...p, t]); }
            else if (ev.type === "reasoning") { setReasoning(p => p + ev.content); }
            else if (ev.type === "answer") { acc += ev.content; setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, content: acc }] : [...p, { role: "assistant", content: acc }]; }); }
            else if (ev.type === "trade_result") { setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, trade: ev.content }] : [...p, { role: "assistant", content: "", trade: ev.content }]; }); }
            else if (ev.type === "sources") { setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, content: l.content, sources: ev.content }] : p; }); }
            else if (ev.type === "done") {
              if (reasoning) setMessages(p => { const l = p[p.length - 1]; return l?.role === "assistant" ? [...p.slice(0, -1), { ...l, reasoning }] : p; });
              setThinking([]); setReasoning(""); setStreaming(false); setSkill("idle");
            }
          } catch { /* skip */ }
        }
      }
    } catch (e) { setMessages(p => [...p, { role: "assistant", content: `网络错误: ${e}` }]); }
    setStreaming(false); setSkill("idle");
  }, [messages, streaming, reasoning]);

  const keyDown = (e: React.KeyboardEvent) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } };

  const hasMessages = messages.length > 0 || !empty;

  return (
    <div className="min-h-screen bg-[#08090b] text-gray-200 font-sans">
      {/* ── ambient light (taste: subtle, not distracting) ── */}
      <div className="fixed inset-0 pointer-events-none" aria-hidden>
        <div className="absolute top-0 left-[20%] w-[500px] h-[300px] bg-amber-600/5 blur-[150px] rounded-full" />
        <div className="absolute bottom-0 right-[10%] w-[400px] h-[250px] bg-amber-700/4 blur-[120px] rounded-full" />
      </div>

      <div className="relative max-w-5xl mx-auto px-5 py-4 flex flex-col h-screen">
        {/* ── header (taste: minimal, asymmetric) ── */}
        <header className="shrink-0 flex items-center justify-between pb-3 border-b border-white/5">
          <div className="flex items-center gap-4">
            <a href="/" className="text-xs text-white/25 hover:text-white/50 transition-colors tracking-wide">← 首页</a>
            <h1 className="text-base font-semibold tracking-tight text-white/90">
              流放知识库
              <span className="ml-2 text-[10px] font-normal text-white/30 tracking-widest uppercase">AI Chat</span>
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <a href="/trade" className="text-[11px] text-white/30 hover:text-emerald-300/70 transition-colors tracking-wide">装备搜索</a>
            <span className={`text-[10px] px-2.5 py-0.5 rounded-full border transition-all duration-500 ${streaming ? (SKILL_COLORS[skill] || "text-white/40 border-white/10 bg-white/5") : "text-white/25 border-white/8 bg-white/[0.02]"}`}>
              {streaming ? (SKILL_LABELS[skill] || skill) : "就绪"}
            </span>
          </div>
        </header>

        {/* ── messages ── */}
        <main className="flex-1 overflow-y-auto py-6 space-y-10">
          {!hasMessages && (
            <div className="flex items-center min-h-[65vh]">
              <div className="max-w-xl">
                <p className="text-sm text-white/20 mb-2 tracking-widest uppercase">Ask anything</p>
                <p className="text-2xl font-medium text-white/60 leading-snug mb-10">
                  PoE2 知识助手 —<br />
                  <span className="text-white/35">BD 设计 · 装备搜索 · 机制百科</span>
                </p>
                <div className="flex flex-wrap gap-2">
                  {QUERY_CHIPS.map((c, i) => (
                    <button key={i} onClick={() => send(c.q)} disabled={streaming}
                      className="text-xs px-4 py-2 rounded-full border border-white/8 text-white/40 bg-white/[0.02] hover:border-amber-500/30 hover:text-amber-200/80 hover:bg-amber-950/20 transition-all duration-300 disabled:opacity-30">
                      {c.q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <article key={i} className={`flex gap-4 ${m.role === "user" ? "flex-row-reverse" : ""}`} style={{ animation: `msgIn 0.35s ease-out ${i * 0.02}s both` }}>
              {/* avatar (taste: simple monogram, no gradients) */}
              <div className={`shrink-0 w-8 h-8 rounded-md flex items-center justify-center text-[11px] font-medium mt-0.5 ${m.role === "user" ? "bg-white/8 text-white/50 border border-white/10" : "bg-amber-950/30 text-amber-400/80 border border-amber-700/30"}`}>
                {m.role === "user" ? "U" : "P"}
              </div>

              <div className={`min-w-0 max-w-[75%] ${m.role === "user" ? "text-right" : ""}`}>
                {/* reasoning */}
                {m.reasoning && (
                  <details className="mb-2">
                    <summary className="text-[10px] text-amber-500/40 cursor-pointer hover:text-amber-400/60 transition-colors tracking-wide uppercase select-none">思考过程</summary>
                    <div className="mt-2 p-3 bg-amber-950/10 border border-amber-800/15 rounded-lg text-[11px] text-amber-500/35 leading-relaxed max-h-44 overflow-y-auto whitespace-pre-wrap">{m.reasoning}</div>
                  </details>
                )}

                {/* content */}
                <div className={`text-sm leading-relaxed rounded-2xl px-4 py-3 ${
                  m.role === "user"
                    ? "bg-amber-950/15 border border-amber-800/20 text-amber-100/80"
                    : "bg-white/[0.02] border border-white/5 text-white/75"
                }`}>
                  <div className="chat-content" dangerouslySetInnerHTML={{ __html: renderContent(m.content) }} />

                  {/* trade cards */}
                  {m.trade && (
                    <div className="mt-3 space-y-2">
                      <p className="text-[10px] text-emerald-400/50 tracking-widest uppercase">交易结果</p>
                      {m.trade.best_match && (
                        <a href={m.trade.best_match.url} target="_blank" rel="noreferrer" className="block p-3 bg-emerald-950/15 border border-emerald-800/25 rounded-xl hover:bg-emerald-950/25 transition-colors">
                          <div className="text-xs text-emerald-300/80 font-medium">{m.trade.best_match.label}</div>
                          <div className="text-[10px] text-white/25 mt-0.5">{m.trade.best_match.count} 件</div>
                        </a>
                      )}
                      {m.trade.alternatives.map((a, j) => (
                        <a key={j} href={a.url} target="_blank" rel="noreferrer" className="block p-2.5 bg-white/[0.02] border border-white/5 rounded-xl hover:bg-white/[0.04] transition-colors">
                          <div className="text-xs text-white/50">{a.label}</div>
                          <div className="text-[10px] text-white/20 mt-0.5">{a.count} 件</div>
                        </a>
                      ))}
                    </div>
                  )}

                  {/* sources */}
                  {m.sources && m.sources.length > 0 && (
                    <details className="mt-3 pt-2 border-t border-white/5">
                      <summary className="text-[10px] text-white/25 cursor-pointer hover:text-white/40 transition-colors">来源 ({m.sources.length})</summary>
                      <div className="mt-2 space-y-1">
                        {m.sources.map((s, j) => <div key={j} className="text-[10px] text-white/20 bg-white/[0.02] rounded px-2 py-1"><span className="text-white/30">[{s.type}]</span> {s.preview}</div>)}
                      </div>
                    </details>
                  )}
                </div>
              </div>
            </article>
          ))}

          {/* ── streaming indicators ── */}
          {reasoning && (
            <article className="flex gap-4">
              <div className="shrink-0 w-8 h-8 rounded-md bg-amber-950/30 border border-amber-700/30 flex items-center justify-center text-[11px] font-medium text-amber-400/80 mt-0.5">P</div>
              <details open className="min-w-0 max-w-[75%] rounded-2xl px-4 py-3 bg-amber-950/10 border border-amber-800/15">
                <summary className="text-[10px] text-amber-500/50 animate-pulse tracking-wide uppercase cursor-pointer">深度思考中</summary>
                <div className="mt-2 text-[11px] text-amber-500/30 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">{reasoning}</div>
              </details>
            </article>
          )}

          {thinking.length > 0 && (
            <article className="flex gap-4">
              <div className="shrink-0 w-8 h-8 rounded-md bg-cyan-950/20 border border-cyan-700/20 flex items-center justify-center text-[11px] font-medium text-cyan-400/60 mt-0.5">S</div>
              <div className="min-w-0 max-w-[75%] rounded-2xl px-4 py-3 bg-cyan-950/8 border border-cyan-800/15">
                <div className="text-[10px] text-cyan-400/40 mb-2 tracking-widest uppercase">检索</div>
                {thinking.map((t, i) => <p key={i} className="text-[11px] text-cyan-500/25 leading-relaxed">{t}</p>)}
              </div>
            </article>
          )}

          {streaming && !reasoning && thinking.length === 0 && (
            <article className="flex gap-4">
              <div className="shrink-0 w-8 h-8 rounded-md bg-amber-950/30 border border-amber-700/30 flex items-center justify-center text-[11px] font-medium text-amber-400/80 mt-0.5">P</div>
              <div className="rounded-2xl px-4 py-3 bg-white/[0.02] border border-white/5 flex gap-1.5 items-center h-10">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500/40 animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500/40 animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500/40 animate-bounce [animation-delay:300ms]" />
              </div>
            </article>
          )}

          <div ref={bottomRef} />
        </main>

        {/* ── input (taste: floating, minimal border) ── */}
        <footer className="shrink-0 pt-3 pb-2 border-t border-white/5">
          <div className="flex gap-3 items-end">
            <input ref={inputRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={keyDown}
              placeholder={streaming ? "回复中..." : "输入问题，Enter 发送"}
              disabled={streaming}
              className="flex-1 bg-transparent border-b border-white/10 px-1 py-3 text-sm text-white/80 placeholder:text-white/20 focus:outline-none focus:border-amber-500/40 transition-colors disabled:opacity-40" />
            <button onClick={() => send(input)} disabled={streaming || !input.trim()}
              className="shrink-0 px-5 py-2.5 rounded-full bg-amber-500/10 border border-amber-500/25 text-amber-400/70 text-sm font-medium hover:bg-amber-500/20 hover:text-amber-300/90 disabled:bg-transparent disabled:border-white/5 disabled:text-white/15 transition-all duration-200">
              {streaming ? "..." : "发送"}
            </button>
          </div>
        </footer>
      </div>

      {/* ── keyframes ── */}
      <style>{`
        @keyframes msgIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        .chat-content .t-h2 { font-size: 1rem; font-weight: 600; color: rgba(255,255,255,0.85); margin-top: 1rem; margin-bottom: 0.25rem; }
        .chat-content .t-h3 { font-size: 0.9rem; font-weight: 600; color: rgba(255,255,255,0.75); margin-top: 0.75rem; margin-bottom: 0.25rem; }
        .chat-content .t-bold { color: rgba(252,211,77,0.85); font-weight: 500; }
        .chat-content .t-li { margin-left: 1rem; list-style: disc; color: rgba(255,255,255,0.55); }
        .chat-content .t-code { font-size: 0.8em; background: rgba(255,255,255,0.04); padding: 1px 4px; border-radius: 3px; color: rgba(252,211,77,0.6); }
        .chat-content .t-tag { font-size: 0.62rem; color: rgba(255,255,255,0.2); background: rgba(255,255,255,0.03); padding: 0 3px; border-radius: 2px; }
        .chat-content .t-tag-guess { color: rgba(252,211,77,0.3); background: rgba(252,211,77,0.04); }
      `}</style>
    </div>
  );
}
