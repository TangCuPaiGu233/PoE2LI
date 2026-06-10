"use client";

import { useState, useRef, useEffect, useCallback } from "react";

interface TradeMatch {
  label: string;
  url: string;
  count: number;
}
interface TradeResult {
  best_match: TradeMatch | null;
  alternatives: TradeMatch[];
  explanation: string;
}
interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: { type: string; preview: string }[];
  reasoning?: string;
  trade?: TradeResult;
}

function getApiUrl(): string {
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}

const SUGGESTIONS = [
  { icon: "⚔️", label: "配一个召唤BD", query: "帮我配一个召唤女巫的开荒BD" },
  { icon: "🔍", label: "搜装备", query: "帮我找一条加2召唤技能等级的项链" },
  { icon: "📖", label: "技能百科", query: "火球是什么技能，有什么效果" },
  { icon: "💡", label: "升华解析", query: "灵魂行者有哪些升华技能" },
  { icon: "💰", label: "价格查询", query: "查一下 Mageblood 的价格" },
  { icon: "🎯", label: "扭曲项链", query: "扭曲项链都能提供什么词条" },
];

function SkillBadge({ name, active }: { name: string; active: boolean }) {
  const labels: Record<string, string> = {
    encyclopedia: "百科",
    build_design: "BD设计",
    trade_search: "交易搜索",
  };
  const colors: Record<string, string> = {
    encyclopedia: "bg-cyan-900/40 text-cyan-400 border-cyan-700/30",
    build_design: "bg-amber-900/40 text-amber-400 border-amber-700/30",
    trade_search: "bg-emerald-900/40 text-emerald-400 border-emerald-700/30",
    idle: "bg-gray-800/40 text-gray-500 border-gray-700/30",
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors duration-500 ${active ? colors[name] || colors.idle : colors.idle}`}>
      {active ? labels[name] || name : "就绪"}
    </span>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState("");
  const [skillName, setSkillName] = useState("idle");
  const [showWelcome, setShowWelcome] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking, reasoning]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const sendQuery = useCallback(async (q: string) => {
    if (!q.trim() || streaming) return;
    setInput("");
    setShowWelcome(false);

    const userMsg: Message = { role: "user", content: q };
    const allMessages = [...messages, userMsg];
    setMessages(allMessages);
    setThinking([]);
    setReasoning("");
    setSkillName("idle");
    setStreaming(true);

    const history = allMessages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));

    let assistantContent = "";
    let currentSkill = "idle";

    try {
      const resp = await fetch(`${getApiUrl()}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, stream: true }),
      });

      const reader = resp.body?.getReader();
      if (!reader) {
        setMessages((prev) => [...prev, { role: "assistant", content: "Error: no response" }]);
        setStreaming(false);
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));

            if (event.type === "thinking") {
              const text = event.content;
              if (text.includes("AI 正在搜索交易市场")) currentSkill = "trade_search";
              else if (text.includes("AI 正在分析")) currentSkill = "encyclopedia";
              else if (text.includes("扩展关联")) currentSkill = currentSkill;
              setSkillName(currentSkill);
              setThinking((prev) => [...prev, text]);
            } else if (event.type === "reasoning") {
              setReasoning((prev) => prev + event.content);
            } else if (event.type === "answer") {
              assistantContent += event.content;
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (last?.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, content: assistantContent }];
                }
                return [...prev, { role: "assistant", content: assistantContent }];
              });
            } else if (event.type === "trade_result") {
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (last?.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, trade: event.content }];
                }
                return [...prev, { role: "assistant", content: "", trade: event.content }];
              });
            } else if (event.type === "sources") {
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (last?.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, content: last.content, sources: event.content }];
                }
                return prev;
              });
            } else if (event.type === "done") {
              if (reasoning) {
                setMessages((prev) => {
                  const last = prev[prev.length - 1];
                  if (last?.role === "assistant") {
                    return [...prev.slice(0, -1), { ...last, reasoning }];
                  }
                  return prev;
                });
              }
              setThinking([]);
              setReasoning("");
              setStreaming(false);
              setSkillName("idle");
            }
          } catch {
            // skip malformed
          }
        }
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", content: `网络错误: ${err}` }]);
    }
    setStreaming(false);
    setSkillName("idle");
  }, [messages, streaming, reasoning]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuery(input);
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0c0f] text-gray-100">
      {/* Background ornament */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden opacity-[0.03]">
        <div className="absolute -top-40 -right-40 w-[600px] h-[600px] rounded-full bg-amber-500 blur-[120px]" />
        <div className="absolute -bottom-40 -left-40 w-[500px] h-[500px] rounded-full bg-emerald-500 blur-[120px]" />
      </div>

      <div className="relative max-w-4xl mx-auto px-4 py-4 flex flex-col h-screen">
        {/* Header */}
        <header className="shrink-0 pb-3 border-b border-gray-800/50">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <a href="/" className="text-gray-600 hover:text-gray-400 text-xs transition-colors">
                ← 首页
              </a>
              <h1 className="text-lg font-bold tracking-wide">
                <span className="bg-gradient-to-r from-amber-400 via-yellow-400 to-amber-500 bg-clip-text text-transparent">
                  流放知识库
                </span>
                <span className="text-gray-700 text-sm font-normal ml-2">AI 对话</span>
              </h1>
            </div>
            <div className="flex items-center gap-2">
              <a href="/trade" className="text-xs text-gray-600 hover:text-emerald-400 transition-colors">装备搜索</a>
              <span className="text-gray-800">|</span>
              <SkillBadge name={skillName} active={streaming} />
            </div>
          </div>
        </header>

        {/* Messages area */}
        <div className="flex-1 overflow-y-auto py-4 space-y-6 scrollbar-thin">
          {messages.length === 0 && showWelcome && (
            <div className="flex items-center justify-center min-h-[60vh]">
              <div className="text-center max-w-lg">
                {/* Ornamental icon */}
                <div className="mb-6 relative inline-block">
                  <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-amber-600/20 to-emerald-600/20 border border-amber-700/30 flex items-center justify-center backdrop-blur">
                    <span className="text-3xl">⚜️</span>
                  </div>
                </div>

                <h2 className="text-xl font-semibold text-gray-300 mb-2">
                  探索流放之路的知识
                </h2>
                <p className="text-sm text-gray-600 mb-8 leading-relaxed">
                  AI 驱动的 PoE2 助手 — 支持装备搜索、BD 设计、机制百科
                </p>

                {/* Suggestion chips */}
                <div className="grid grid-cols-2 gap-2">
                  {SUGGESTIONS.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => sendQuery(s.query)}
                      disabled={streaming}
                      className="text-left p-3 bg-gray-900/60 border border-gray-800/60 rounded-xl hover:border-amber-700/40 hover:bg-gray-900/80 transition-all duration-200 group disabled:opacity-40"
                    >
                      <span className="text-sm mr-2">{s.icon}</span>
                      <span className="text-xs text-gray-400 group-hover:text-gray-300 transition-colors">{s.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div
              key={i}
              className={`flex gap-3 ${m.role === "user" ? "justify-end" : "justify-start"}`}
              style={{ animation: "fadeIn 0.3s ease-out" }}
            >
              {/* Avatar */}
              {m.role === "assistant" && (
                <div className="shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-amber-600/30 to-amber-700/30 border border-amber-700/40 flex items-center justify-center mt-1">
                  <span className="text-xs">⚜️</span>
                </div>
              )}

              <div className={`max-w-[80%] ${m.role === "user" ? "order-first" : ""}`}>
                {/* Message bubble */}
                <div
                  className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    m.role === "user"
                      ? "bg-gradient-to-br from-amber-700/30 to-amber-800/20 border border-amber-600/30 text-amber-50"
                      : "bg-gray-900/60 border border-gray-800/60 text-gray-200"
                  }`}
                >
                  {/* Reasoning */}
                  {m.reasoning && (
                    <details className="mb-3">
                      <summary className="text-[11px] text-amber-500/60 cursor-pointer hover:text-amber-400/80 transition-colors select-none">
                        🧠 思考过程
                      </summary>
                      <div className="mt-2 p-3 bg-amber-950/20 border border-amber-800/20 rounded-lg text-[11px] text-amber-500/50 leading-relaxed max-h-48 overflow-y-auto">
                        {m.reasoning}
                      </div>
                    </details>
                  )}

                  {/* Content with basic markdown */}
                  <div
                    className="whitespace-pre-wrap [&_strong]:text-amber-300 [&_h3]:text-amber-200 [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_ul]:list-disc [&_ul]:pl-4 [&_code]:bg-gray-800/50 [&_code]:px-1 [&_code]:rounded [&_code]:text-amber-300/70"
                    dangerouslySetInnerHTML={{
                      __html: m.content
                        .replace(/### (.+)/g, '<h3 class="text-amber-200 font-semibold mt-3 mb-1">$1</h3>')
                        .replace(/## (.+)/g, '<h3 class="text-amber-200 font-semibold mt-3 mb-1">$1</h3>')
                        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-amber-300">$1</strong>')
                        .replace(/^- (.+)/gm, '<li class="ml-4 list-disc">$1</li>')
                        .replace(/`([^`]+)`/g, '<code class="bg-gray-800/50 px-1 rounded text-amber-300/70">$1</code>')
                        .replace(/\[资料\]/g, '<span class="text-[10px] text-gray-600 bg-gray-800/50 px-1 rounded">资料</span>')
                        .replace(/\[推测\]/g, '<span class="text-[10px] text-amber-600/70 bg-amber-950/30 px-1 rounded">推测</span>'),
                    }}
                  />

                  {/* Trade results */}
                  {m.trade && (
                    <div className="mt-3 p-3 bg-emerald-950/20 border border-emerald-800/30 rounded-xl">
                      <div className="text-xs text-emerald-400 font-medium mb-2 flex items-center gap-1">
                        <span>🔍</span> 交易搜索结果
                      </div>
                      {m.trade.best_match && (
                        <a
                          href={m.trade.best_match.url}
                          target="_blank"
                          rel="noreferrer"
                          className="block p-2.5 bg-emerald-900/20 border border-emerald-700/30 rounded-lg mb-2 hover:bg-emerald-900/30 transition-colors"
                        >
                          <div className="text-xs text-emerald-300 font-medium">{m.trade.best_match.label}</div>
                          <div className="text-[11px] text-gray-500 mt-0.5">{m.trade.best_match.count} 件</div>
                        </a>
                      )}
                      {m.trade.alternatives.map((alt, j) => (
                        <a
                          key={j}
                          href={alt.url}
                          target="_blank"
                          rel="noreferrer"
                          className="block p-2 bg-gray-800/40 border border-gray-700/30 rounded-lg mb-1.5 hover:bg-gray-800/60 transition-colors"
                        >
                          <div className="text-xs text-gray-300">{alt.label}</div>
                          <div className="text-[11px] text-gray-600 mt-0.5">{alt.count} 件</div>
                        </a>
                      ))}
                    </div>
                  )}

                  {/* Sources */}
                  {m.sources && m.sources.length > 0 && (
                    <details className="mt-3 pt-2 border-t border-gray-800/50">
                      <summary className="text-[11px] text-gray-600 cursor-pointer hover:text-gray-500 transition-colors">
                        参考来源 ({m.sources.length})
                      </summary>
                      <div className="mt-2 space-y-1">
                        {m.sources.map((s, j) => (
                          <div key={j} className="text-[10px] text-gray-700 bg-gray-900/40 rounded px-2 py-1">
                            <span className="text-gray-500">[{s.type}]</span> {s.preview}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              </div>

              {/* User avatar */}
              {m.role === "user" && (
                <div className="shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-gray-700/30 to-gray-600/30 border border-gray-600/40 flex items-center justify-center mt-1">
                  <span className="text-xs">👤</span>
                </div>
              )}
            </div>
          ))}

          {/* Streaming indicators */}
          {reasoning && (
            <div className="flex gap-3 justify-start">
              <div className="shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-amber-600/30 to-amber-700/30 border border-amber-700/40 flex items-center justify-center mt-1">
                <span className="text-xs">⚜️</span>
              </div>
              <details open className="max-w-[80%] rounded-2xl px-4 py-3 bg-amber-950/15 border border-amber-800/20">
                <summary className="text-[11px] text-amber-500/70 cursor-pointer animate-pulse">
                  🧠 深度思考中...
                </summary>
                <p className="mt-2 text-[11px] text-amber-500/40 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                  {reasoning}
                </p>
              </details>
            </div>
          )}

          {thinking.length > 0 && (
            <div className="flex gap-3 justify-start">
              <div className="shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-600/20 to-cyan-700/20 border border-cyan-700/30 flex items-center justify-center mt-1">
                <span className="text-xs">🔍</span>
              </div>
              <div className="max-w-[80%] rounded-2xl px-4 py-3 bg-cyan-950/15 border border-cyan-800/20">
                <div className="text-[11px] text-cyan-400/60 mb-2">检索中...</div>
                <div className="space-y-1">
                  {thinking.map((t, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="w-1 h-1 rounded-full bg-cyan-600/50" />
                      <p className="text-[11px] text-cyan-500/40">{t}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Streaming answer placeholder */}
          {streaming && !reasoning && thinking.length === 0 && (
            <div className="flex gap-3 justify-start">
              <div className="shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-amber-600/30 to-amber-700/30 border border-amber-700/40 flex items-center justify-center mt-1">
                <span className="text-xs">⚜️</span>
              </div>
              <div className="rounded-2xl px-4 py-3 bg-gray-900/60 border border-gray-800/60">
                <div className="flex gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-600/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-600/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-600/60 animate-bounce" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="shrink-0 pt-3 border-t border-gray-800/50">
          <div className="flex gap-2 items-end">
            <div className="flex-1 relative">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={streaming ? "AI 正在回复..." : "输入问题，Enter 发送..."}
                disabled={streaming}
                className="w-full bg-gray-900/60 border border-gray-700/60 rounded-2xl px-4 py-3 pr-10 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-amber-600/50 focus:ring-1 focus:ring-amber-600/30 disabled:opacity-50 transition-all"
              />
              {input.length > 0 && (
                <button
                  onClick={() => setInput("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 text-xs"
                >
                  ✕
                </button>
              )}
            </div>
            <button
              onClick={() => sendQuery(input)}
              disabled={streaming || !input.trim()}
              className="shrink-0 bg-gradient-to-r from-amber-600 to-amber-700 hover:from-amber-500 hover:to-amber-600 disabled:from-gray-700 disabled:to-gray-800 disabled:text-gray-600 text-white px-5 py-3 rounded-2xl text-sm font-medium transition-all duration-200 flex items-center gap-1.5 disabled:cursor-not-allowed shadow-lg shadow-amber-900/20"
            >
              {streaming ? (
                <span className="flex gap-1">
                  <span className="w-1 h-1 rounded-full bg-white/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-1 h-1 rounded-full bg-white/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-1 h-1 rounded-full bg-white/60 animate-bounce" style={{ animationDelay: "300ms" }} />
                </span>
              ) : (
                <>
                  <span>发送</span>
                  <span className="text-xs opacity-60">↵</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
