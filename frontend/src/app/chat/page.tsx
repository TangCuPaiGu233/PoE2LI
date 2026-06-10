"use client";

import { useState, useRef, useEffect } from "react";

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

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState("");  // model's chain-of-thought
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  async function sendMessage() {
    const q = input.trim();
    if (!q || streaming) return;
    setInput("");

    const userMsg: Message = { role: "user", content: q };
    const allMessages = [...messages, userMsg];
    setMessages(allMessages);
    setThinking([]);
    setStreaming(true);

    // Build history for API
    const history = allMessages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));

    let assistantContent = "";

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
          const jsonStr = line.slice(6);
          try {
            const event = JSON.parse(jsonStr);

            if (event.type === "reasoning") {
              setReasoning((prev) => prev + event.content);
            } else if (event.type === "thinking") {
              setThinking((prev) => [...prev, event.content]);
            } else if (event.type === "answer") {
              assistantContent += event.content;
              // Update the last assistant message or create new one
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (last?.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, content: assistantContent }];
                }
                return [...prev, { role: "assistant", content: assistantContent }];
              });
            } else if (event.type === "sources") {
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (last?.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, content: last.content, sources: event.content }];
                }
                return prev;
              });
            } else if (event.type === "trade_result") {
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (last?.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, trade: event.content }];
                }
                return [...prev, { role: "assistant", content: "", trade: event.content }];
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
            }
          } catch {
            // skip malformed JSON
          }
        }
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", content: `网络错误: ${err}` }]);
    }
    setStreaming(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950 text-gray-100">
      <div className="max-w-3xl mx-auto px-4 py-4 flex flex-col h-screen">
        {/* Header */}
        <header className="text-center py-3 border-b border-gray-800 shrink-0">
          <a href="/" className="text-gray-500 hover:text-gray-300 text-sm">
            ← 返回首页
          </a>
          <h1 className="text-xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-500 bg-clip-text text-transparent">
            流放知识库
          </h1>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto py-4 space-y-4">
          {messages.length === 0 && (
            <div className="text-center py-16 text-gray-600">
              <p className="text-4xl mb-4">🗡️</p>
              <p className="text-sm">问任何 PoE2 问题：装备推荐、技能机制、BD 建议、装备搜索…</p>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-xl px-4 py-3 ${
                m.role === "user"
                  ? "bg-emerald-700/30 border border-emerald-600/30"
                  : m.role === "assistant"
                  ? "bg-gray-800/50 border border-gray-700/30"
                  : "bg-gray-800/20 border border-gray-700/20"
              }`}>
                {m.role === "user" ? (
                  <p className="text-sm whitespace-pre-wrap">{m.content}</p>
                ) : (
                  <div className="text-sm whitespace-pre-wrap leading-relaxed">
                    {m.reasoning && (
                      <details className="mb-2">
                        <summary className="text-xs text-amber-400/70 cursor-pointer hover:text-amber-400">
                          🧠 思考过程
                        </summary>
                        <div className="mt-1 p-2 bg-amber-900/10 border border-amber-700/20 rounded text-xs text-amber-400/60">
                          {m.reasoning}
                        </div>
                      </details>
                    )}
                    {m.content}
                    {m.trade && (
                      <div className="mt-2 p-3 bg-emerald-900/20 border border-emerald-700/30 rounded-lg">
                        <div className="text-xs text-emerald-400 font-medium mb-2">🔍 交易搜索结果</div>
                        {m.trade.best_match && (
                          <a href={m.trade.best_match.url} target="_blank" rel="noreferrer"
                             className="block p-2 bg-emerald-900/30 border border-emerald-600/30 rounded mb-2 hover:bg-emerald-900/40 transition-colors">
                            <div className="text-xs text-emerald-300 font-medium">{m.trade.best_match.label}</div>
                            <div className="text-xs text-gray-400 mt-0.5">{m.trade.best_match.count} 件物品</div>
                          </a>
                        )}
                        {m.trade.alternatives.map((alt: TradeMatch, j: number) => (
                          <a key={j} href={alt.url} target="_blank" rel="noreferrer"
                             className="block p-2 bg-gray-800/50 border border-gray-700/30 rounded mb-1 hover:bg-gray-700/50 transition-colors">
                            <div className="text-xs text-gray-300">{alt.label}</div>
                            <div className="text-xs text-gray-500 mt-0.5">{alt.count} 件物品</div>
                          </a>
                        ))}
                      </div>
                    )}
                    {m.sources && m.sources.length > 0 && (
                      <details className="mt-2 pt-2 border-t border-gray-700/30">
                        <summary className="text-xs text-gray-500 cursor-pointer">
                          参考来源 ({m.sources.length})
                        </summary>
                        <div className="mt-1 space-y-1">
                          {m.sources.map((s, j) => (
                            <div key={j} className="text-xs text-gray-600 bg-gray-900/50 rounded px-2 py-1">
                              [{s.type}] {s.preview}
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Model reasoning streaming */}
          {reasoning && (
            <div className="flex justify-start">
              <details open className="max-w-[85%] rounded-xl px-4 py-3 bg-amber-900/10 border border-amber-700/20">
                <summary className="text-xs text-amber-400 cursor-pointer animate-pulse">
                  🧠 深度思考中...
                </summary>
                <p className="mt-2 text-xs text-amber-400/60 whitespace-pre-wrap">{reasoning}</p>
              </details>
            </div>
          )}

          {/* Retrieval progress indicator */}
          {thinking.length > 0 && (
            <div className="flex justify-start">
              <details open className="max-w-[85%] rounded-xl px-4 py-3 bg-cyan-900/20 border border-cyan-700/30">
                <summary className="text-xs text-cyan-400 cursor-pointer">
                  🔍 检索中...
                </summary>
                <div className="mt-2 space-y-1">
                  {thinking.map((t, i) => (
                    <p key={i} className="text-xs text-cyan-400/70">{t}</p>
                  ))}
                </div>
              </details>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="shrink-0 py-3 border-t border-gray-800">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={streaming ? "AI 正在回复..." : "输入问题... (Enter 发送)"}
              disabled={streaming}
              className="flex-1 bg-gray-800/50 border border-gray-700 rounded-xl px-4 py-3 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 disabled:opacity-50"
            />
            <button
              onClick={sendMessage}
              disabled={streaming || !input.trim()}
              className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white px-5 py-3 rounded-xl text-sm font-medium transition shrink-0"
            >
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
