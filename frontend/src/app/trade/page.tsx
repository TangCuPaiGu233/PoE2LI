"use client";

import { useState } from "react";

function getApiUrl(): string {
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}

interface TradeResult {
  trade_url?: string;
  search_id?: string;
  total_results?: number;
  intent_summary?: string;
  filters?: Record<string, unknown>;
  expires_in?: number;
  error?: string;
}

const EXAMPLE_QUERIES = [
  "帮我找一条加2召唤兽等级的项链",
  "找一个带生命和抗性的戒指",
  "加3法术技能等级的法杖",
  "80生命以上火抗鞋子",
  "加移速和闪避的头盔",
  "物理伤害双手剑",
];

export default function TradePage() {
  const [query, setQuery] = useState("");
  const [league] = useState("Standard");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<TradeResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async (e?: React.FormEvent, overrideQuery?: string) => {
    if (e) e.preventDefault();
    const q = overrideQuery || query;
    if (!q.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${getApiUrl()}/api/trade/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q.trim(), league }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setError(errData.detail || `HTTP ${res.status}`);
        return;
      }

      const data: TradeResult = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }

      setResults((prev) => [data, ...prev].slice(0, 10));
    } catch (err) {
      setError(`网络错误: ${err instanceof Error ? err.message : "未知"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950 text-gray-100">
      <div className="max-w-3xl mx-auto px-4 py-8">
        {/* Header */}
        <header className="text-center mb-8">
          <a href="/" className="text-gray-500 hover:text-gray-300 text-sm mb-4 inline-block">
            ← 返回首页
          </a>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-500 bg-clip-text text-transparent">
            装备搜索
          </h1>
          <p className="text-gray-500 mt-1 text-sm">
            用自然语言描述你想要的装备，直接跳转到 PoE2 官方交易站
          </p>
        </header>

        {/* Search Form */}
        <form onSubmit={handleSearch} className="mb-6">
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="描述你要找的装备，例如：加2召唤兽等级的项链"
              className="w-full bg-gray-800/50 border border-gray-700 rounded-xl px-4 py-3 pr-24 text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 transition"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="absolute right-2 top-1/2 -translate-y-1/2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 text-white px-4 py-1.5 rounded-lg text-sm font-medium transition"
            >
              {loading ? (
                <span className="animate-pulse-glow">搜索中...</span>
              ) : (
                "搜索"
              )}
            </button>
          </div>
        </form>

        {/* Quick Examples */}
        <div className="mb-8">
          <p className="text-xs text-gray-600 mb-2">试试这些：</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_QUERIES.map((ex) => (
              <button
                key={ex}
                onClick={() => handleSearch(undefined, ex)}
                disabled={loading}
                className="text-xs bg-gray-800/60 hover:bg-gray-700/60 border border-gray-700/50 text-gray-400 hover:text-gray-200 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-900/20 border border-red-800/50 rounded-xl p-4 mb-6">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        )}

        {/* Results */}
        {results.length > 0 && (
          <div className="space-y-3">
            <p className="text-xs text-gray-600 mb-2">搜索结果（最新在前）</p>
            {results.map((r, i) => (
              <div
                key={i}
                className="bg-gray-800/40 border border-gray-700/50 rounded-xl p-4 hover:border-emerald-600/30 transition"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-gray-300 text-sm mb-1">
                      {r.intent_summary}
                    </p>
                    <div className="flex items-center gap-3 text-xs text-gray-500">
                      {r.total_results !== undefined && (
                        <span>
                          找到 <span className="text-emerald-400 font-medium">{r.total_results}</span> 个结果
                        </span>
                      )}
                      {r.expires_in && (
                        <span>链接有效期 ~{Math.floor(r.expires_in / 60)} 分钟</span>
                      )}
                    </div>
                  </div>
                  {r.trade_url && (
                    <a
                      href={r.trade_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-600/40 text-emerald-400 px-4 py-2 rounded-lg text-sm font-medium transition"
                    >
                      打开交易站 →
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {results.length === 0 && !error && !loading && (
          <div className="text-center py-16 text-gray-600">
            <p className="text-4xl mb-4">🔍</p>
            <p className="text-sm">输入装备需求，AI 帮你生成交易站搜索链接</p>
          </div>
        )}
      </div>
    </div>
  );
}
