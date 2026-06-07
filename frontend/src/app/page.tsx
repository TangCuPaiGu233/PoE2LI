"use client";

import { useState, useEffect, useCallback } from "react";

// Auto-detect API URL: same host, port 8000
function getApiUrl(): string {
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}

interface BuildInfo {
  className?: string;
  ascendClassName?: string;
  level?: string;
}

interface PlayerStats {
  [key: string]: number | string;
}

interface Homework {
  core_idea: string;
  core_items: string;
  budget_alternatives: string;
  talent_highlights: string;
  strength_review: string;
}

interface BuildData {
  id?: number;
  build: BuildInfo;
  playerStats: PlayerStats;
  homework?: Homework;
  treeSpecs?: { nodes: number[] }[];
  skillSets?: { gems: { nameSpec?: string; level?: number }[] }[];
  items?: { id?: string; rarity?: string; name?: string }[];
  created_at?: string;
}

interface BuildSummary {
  id: number;
  status: string;
  build: BuildInfo;
  created_at?: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export default function Home() {
  const [pobCode, setPobCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState("");
  const [result, setResult] = useState<BuildData | null>(null);
  const [error, setError] = useState<{ message: string; reason?: string } | null>(null);
  const [history, setHistory] = useState<BuildSummary[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [pobValid, setPobValid] = useState<boolean | null>(null);
  
  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  // Reset chat when switching builds
  useEffect(() => {
    setChatMessages([]);
    setChatInput("");
  }, [result?.id]);

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch(`${getApiUrl()}/api/builds`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
      }
    } catch {
      // Ignore
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  // Validate PoB code format on input
  useEffect(() => {
    if (!pobCode.trim()) {
      setPobValid(null);
      return;
    }
    const trimmed = pobCode.trim();
    // Valid if it's a pobb.in URL, poe.ninja URL, or starts with eN
    const isPobbin = /^https?:\/\/pobb\.in\/[a-zA-Z0-9_-]+/.test(trimmed);
    const isPoeNinja = /^https?:\/\/poe\.ninja\/poe2\/builds\/[a-zA-Z0-9_-]+\/character\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+/.test(trimmed);
    const isBase64 = trimmed.startsWith("eN") && trimmed.length > 100;
    
    // Also allow raw base64 that might start with eN or have some spaces
    const isBase64Relaxed = trimmed.replace(/\s/g, '').startsWith("eN") && trimmed.length > 100;
    
    setPobValid(isPobbin || isPoeNinja || isBase64 || isBase64Relaxed);
  }, [pobCode]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pobCode.trim() || loading) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setLoadingStep("解码 PoB 分享码...");

    try {
      const res = await fetch(`${getApiUrl()}/api/builds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pob_code: pobCode.trim() }),
      });

      if (!res.ok) {
        const err = await res.json();
        const detail = err.detail;
        if (typeof detail === "object") {
          throw { message: detail.error, reason: detail.reason };
        }
        throw { message: detail || "解码失败" };
      }

      const data = await res.json();
      setLoadingStep("AI 正在生成攻略...");

      // Poll until homework is generated
      const buildId = data.id;
      let isDone = false;
      let attempts = 0;
      const maxAttempts = 150; // 150 * 2s = 300s max (DeepSeek V4 Flash can take 2+ min)

      while (!isDone && attempts < maxAttempts) {
        attempts++;
        const fullRes = await fetch(`${getApiUrl()}/api/builds/${buildId}`);
        if (!fullRes.ok) throw { message: "获取状态失败" };
        
        const fullData = await fullRes.json();
        
        if (fullData.status === "done") {
          setResult(fullData);
          isDone = true;
        } else if (fullData.status === "failed") {
          throw { message: "AI 攻略生成失败，请重试" };
        } else {
          // Still pending, wait 2 seconds and show temporary result (without homework)
          setResult(fullData);
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }

      if (!isDone) {
        throw { message: "AI 生成超时，请稍后在历史记录中查看" };
      }

      loadHistory();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "message" in err) {
        setError(err as { message: string; reason?: string });
      } else {
        setError({ message: err instanceof Error ? err.message : "未知错误" });
      }
    } finally {
      setLoading(false);
      setLoadingStep("");
    }
  };

  const loadBuild = async (id: number) => {
    setLoading(true);
    setError(null);
    setLoadingStep("加载中...");
    try {
      const res = await fetch(`${getApiUrl()}/api/builds/${id}`);
      if (res.ok) {
        setResult(await res.json());
      } else {
        setError({ message: "加载失败" });
      }
    } catch {
      setError({ message: "加载失败" });
    } finally {
      setLoading(false);
      setLoadingStep("");
    }
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        const trimmed = text.trim();
        if (trimmed.startsWith("eN") || /^https?:\/\/(pobb\.in|poe\.ninja)/.test(trimmed)) {
          setPobCode(trimmed);
        }
      }
    } catch {
      // Clipboard access denied
    }
  };

  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || chatLoading || !result?.id) return;

    const userMessage = chatInput.trim();
    setChatInput("");
    setChatMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setChatLoading(true);

    try {
      const res = await fetch(`${getApiUrl()}/api/builds/${result.id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ build_id: result.id, question: userMessage }),
      });

      if (!res.ok) throw new Error("请求失败");
      
      const data = await res.json();
      setChatMessages((prev) => [...prev, { role: "assistant", content: data.answer }]);
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "抱歉，网络似乎出了点问题，请稍后再试。" },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  const copyShareLink = () => {
    if (result?.id) {
      const url = `${window.location.origin}?build=${result.id}`;
      navigator.clipboard.writeText(url);
    }
  };

  const stats = result?.playerStats || {};
  const gems = result?.skillSets?.flatMap((s) => s.gems?.filter((g) => g.nameSpec) || []) || [];

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950 text-gray-100">
      <div className="max-w-5xl mx-auto px-4 py-8">
        {/* Header */}
        <header className="text-center mb-8">
          <h1 className="text-3xl font-bold bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">
            流放漓 PoE2LI
          </h1>
          <p className="text-gray-500 mt-1 text-sm">Path of Exile 2 智能构建分析工具</p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
          {/* Main */}
          <div>
            {/* Input */}
            <form onSubmit={handleSubmit} className="mb-6">
              <div className="relative">
                <textarea
                  value={pobCode}
                  onChange={(e) => setPobCode(e.target.value)}
                  placeholder="粘贴 PoB 分享码 (eNp...) 或 pobb.in / poe.ninja 链接..."
                  rows={3}
                  className="w-full p-4 pr-24 bg-gray-900 border border-gray-700 rounded-xl text-sm font-mono focus:outline-none focus:border-amber-500 resize-none"
                />
                <div className="absolute right-3 top-3 flex gap-2">
                  <button
                    type="button"
                    onClick={handlePaste}
                    className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                  >
                    粘贴
                  </button>
                </div>
              </div>

              {/* Validation feedback */}
              {pobValid === false && pobCode.length > 10 && (
                <p className="mt-2 text-xs text-red-400">
                  支持 PoB 分享码 (eN 开头) 或 https://pobb.in/ 或 https://poe.ninja/ 链接
                </p>
              )}
              {pobValid === true && (
                <p className="mt-2 text-xs text-green-400">✓ 格式正确</p>
              )}

              <button
                type="submit"
                disabled={loading || !pobValid}
                className="mt-3 w-full py-3 bg-gradient-to-r from-amber-500 to-orange-500 text-gray-900 font-semibold rounded-xl hover:from-amber-400 hover:to-orange-400 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    {loadingStep || "处理中..."}
                  </span>
                ) : (
                  "解析并生成攻略"
                )}
              </button>
            </form>

            {/* Error */}
            {error && (
              <div className="mb-6 p-4 bg-red-950/50 border border-red-800 rounded-xl">
                <div className="flex items-start gap-3">
                  <span className="text-red-400 text-lg">⚠</span>
                  <div>
                    <p className="text-red-300 font-medium">{error.message}</p>
                    {error.reason && (
                      <p className="text-red-400/70 text-xs mt-1">错误类型: {error.reason}</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Result */}
            {result && (
              <div className="space-y-4">
                {/* Build Info Card */}
                <div className="p-5 bg-gray-900/80 border border-gray-800 rounded-xl">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-bold text-amber-400">
                      {result.build.className} / {result.build.ascendClassName}
                    </h2>
                    <span className="text-xs text-gray-500">Lv.{result.build.level}</span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <Stat label="生命" value={formatNum(stats.Life as number)} color="text-red-400" />
                    <Stat label="魔力" value={formatNum(stats.Mana as number)} color="text-blue-400" />
                    <Stat label="DPS" value={formatNum(stats.TotalDPS as number)} color="text-yellow-400" />
                    <Stat label="护甲" value={formatNum(stats.Armour as number)} color="text-gray-400" />
                    <Stat label="力量" value={String(stats.Str || 0)} color="text-red-300" />
                    <Stat label="敏捷" value={String(stats.Dex || 0)} color="text-green-300" />
                    <Stat label="智慧" value={String(stats.Int || 0)} color="text-blue-300" />
                    <Stat
                      label="抗性"
                      value={`${stats.FireResist || 0}/${stats.ColdResist || 0}/${stats.LightningResist || 0}`}
                      color="text-orange-300"
                    />
                  </div>
                </div>

                {/* Gems */}
                {gems.length > 0 && (
                  <div className="p-5 bg-gray-900/80 border border-gray-800 rounded-xl">
                    <h3 className="text-sm font-semibold text-gray-400 mb-3">技能宝石</h3>
                    <div className="flex flex-wrap gap-2">
                      {gems.map((g, i) => (
                        <span
                          key={i}
                          className="px-2.5 py-1 bg-gray-800 border border-gray-700 rounded-lg text-xs"
                        >
                          {g.nameSpec}
                          <span className="text-gray-500 ml-1">Lv{g.level}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Homework */}
                {result.homework && (
                  <div className="p-5 bg-gray-900/80 border border-gray-800 rounded-xl">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-sm font-semibold text-gray-400">AI 攻略</h3>
                      <button
                        onClick={copyShareLink}
                        className="text-xs text-gray-500 hover:text-amber-400 transition-colors"
                      >
                        复制分享链接
                      </button>
                    </div>
                    <div className="space-y-4">
                      <HomeworkBlock title="核心思路" content={result.homework.core_idea} icon="💡" />
                      <HomeworkBlock title="核心装备" content={result.homework.core_items} icon="🛡" />
                      <HomeworkBlock title="平价替代" content={result.homework.budget_alternatives} icon="💰" />
                      <HomeworkBlock title="天赋亮点" content={result.homework.talent_highlights} icon="🌳" />
                      <HomeworkBlock title="强度评价" content={result.homework.strength_review} icon="📊" />
                    </div>
                  </div>
                )}

                {/* AI Chat / Q&A */}
                {result.homework && (
                  <div className="p-5 bg-gray-900/80 border border-gray-800 rounded-xl flex flex-col h-[400px]">
                    <h3 className="text-sm font-semibold text-gray-400 mb-4 flex items-center gap-2">
                      <span>🤖</span> 针对此 Build 向 AI 提问
                    </h3>
                    
                    <div className="flex-1 overflow-y-auto space-y-4 mb-4 pr-2 scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent">
                      {chatMessages.length === 0 ? (
                        <div className="h-full flex items-center justify-center text-xs text-gray-600">
                          你可以问：“这套 BD 前期怎么开荒？” 或 “缺蓝怎么解决？”
                        </div>
                      ) : (
                        chatMessages.map((msg, idx) => (
                          <div
                            key={idx}
                            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                          >
                            <div
                              className={`max-w-[85%] p-3 rounded-2xl text-sm ${
                                msg.role === "user"
                                  ? "bg-amber-500/20 text-amber-100 rounded-tr-sm"
                                  : "bg-gray-800 text-gray-300 rounded-tl-sm whitespace-pre-line"
                              }`}
                            >
                              {msg.content}
                            </div>
                          </div>
                        ))
                      )}
                      {chatLoading && (
                        <div className="flex justify-start">
                          <div className="bg-gray-800 text-gray-400 p-3 rounded-2xl rounded-tl-sm text-xs flex gap-1">
                            <span className="animate-bounce">.</span>
                            <span className="animate-bounce delay-100">.</span>
                            <span className="animate-bounce delay-200">.</span>
                          </div>
                        </div>
                      )}
                    </div>
                    
                    <form onSubmit={handleChatSubmit} className="relative mt-auto">
                      <input
                        type="text"
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        placeholder="向 AI 提问..."
                        className="w-full bg-gray-950 border border-gray-700 rounded-lg py-2.5 pl-4 pr-12 text-sm focus:outline-none focus:border-amber-500/50 transition-colors"
                        disabled={chatLoading}
                      />
                      <button
                        type="submit"
                        disabled={!chatInput.trim() || chatLoading}
                        className="absolute right-2 top-1.5 p-1.5 text-gray-400 hover:text-amber-400 disabled:opacity-30 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                        </svg>
                      </button>
                    </form>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Sidebar - History */}
          <div className="lg:sticky lg:top-8 lg:self-start">
            <div className="p-4 bg-gray-900/80 border border-gray-800 rounded-xl">
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="w-full flex items-center justify-between text-sm font-semibold text-gray-400 mb-3"
              >
                <span>历史记录 ({history.length})</span>
                <span className="text-xs">{showHistory ? "▲" : "▼"}</span>
              </button>

              {showHistory && (
                <div className="space-y-2 max-h-[60vh] overflow-y-auto">
                  {history.length === 0 ? (
                    <p className="text-xs text-gray-600 text-center py-4">暂无记录</p>
                  ) : (
                    history.map((b) => (
                      <button
                        key={b.id}
                        onClick={() => loadBuild(b.id)}
                        className={`w-full p-3 rounded-lg text-left text-xs transition-colors ${
                          result?.id === b.id
                            ? "bg-amber-500/10 border border-amber-500/30"
                            : "bg-gray-800/50 border border-transparent hover:bg-gray-800"
                        }`}
                      >
                        <div className="font-medium text-gray-200">
                          {b.build.className}{" "}
                          <span className="text-gray-500">Lv.{b.build.level}</span>
                        </div>
                        <div className="text-gray-500 mt-0.5">
                          {b.build.ascendClassName || "无升华"}
                        </div>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, color = "text-white" }: { label: string; value: string; color?: string }) {
  return (
    <div className="p-2.5 bg-gray-800/50 rounded-lg">
      <div className="text-[10px] text-gray-500 mb-0.5">{label}</div>
      <div className={`text-sm font-bold ${color}`}>{value}</div>
    </div>
  );
}

function HomeworkBlock({ title, content, icon }: { title: string; content: string; icon: string }) {
  if (!content) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold text-gray-400 mb-1.5">
        {icon} {title}
      </h4>
      <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">{content}</p>
    </div>
  );
}

function formatNum(n: number): string {
  if (!n) return "0";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toFixed(0);
}
