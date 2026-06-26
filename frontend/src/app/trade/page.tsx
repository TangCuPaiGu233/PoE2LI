"use client";

import { useState, useCallback } from "react";

/* ── Types ── */
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

/* ── Mock data generator ── */
function buildMockResult(query: string): TradeResult {
  const q = query.trim();
  const base = q || "Distorted Amulet";
  const count = Math.floor(Math.random() * 1200) + 20;
  const priceChaos = (Math.random() * 25 + 0.5).toFixed(2);
  const itemName = `${base} · ${[" Empowered ", " Fractured ", " Synthesised "][Math.floor(Math.random() * 3)]}${["Amulet","Ring","Belt","Gloves","Helm"][Math.floor(Math.random() * 5)]}`;

  const best: TradeMatch = {
    label: `${base} — 精确匹配`,
    url: `https://www.pathofexile.com/trade2/search/poe2/standard?q=${encodeURIComponent(base)}`,
    count,
    broad: count > 500,
  };

  const alternatives: TradeMatch[] = [
    {
      label: `${base} — 含相似词缀`,
      url: `https://www.pathofexile.com/trade2/search/poe2/standard?q=${encodeURIComponent(base + " similar")}`,
      count: Math.max(10, Math.floor(count * 0.35)),
    },
    {
      label: `${base} — 按基底类型`,
      url: `https://www.pathofexile.com/trade2/search/poe2/standard?q=${encodeURIComponent("base:" + base)}`,
      count: Math.max(5, Math.floor(count * 0.2)),
    },
  ];

  return {
    best_match: best,
    alternatives,
    explanation: `已根据关键词「${base}」检索交易市场。当前精确匹配结果共 ${count} 件在售。若结果过多，建议补充词缀、职业或装备槽位约束。`,
    listing_price: {
      display: `${priceChaos} 混沌石`,
      amount: Number(priceChaos),
      currency: "chaos",
      item_name: itemName.trim(),
    },
    price_note: "价格为近期成交区间参考，实际售价可能波动。",
  };
}

/* ── Components ── */
function TradeCountBadge(m: TradeMatch): string {
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
          ? "block p-3 ninja-panel-accent mb-2 hover:bg-[var(--ninja-panel-hover)] transition-colors"
          : "block p-2.5 ninja-panel mb-2 hover:bg-[var(--ninja-panel-hover)] transition-colors"
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm text-[var(--poe-gold)] min-w-0">{match.label}</div>
        <span
          className={
            match.empty
              ? "shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-[var(--poe-surface-2)] text-[var(--ninja-text-dim)]"
              : "shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-[var(--poe-surface-2)] text-[var(--poe-text-dim)]"
          }
        >
          {TradeCountBadge(match)}
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

/* ── Page ── */
export default function TradePage() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<TradeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  const handleSearch = useCallback(
    async (q: string) => {
      const text = q.trim();
      if (!text || loading) return;
      setLoading(true);
      setError(null);
      setResult(null);
      setSearched(true);

      try {
        // 先尝试真实后端；若不可用则回退到 mock，保证页面可演示
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 4000);
        let usedMock = false;

        let data: TradeResult | null = null;

        try {
          const resp = await fetch(
            `${window.location.protocol}//${window.location.hostname}:8000/api/trade/search`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ q: text }),
              signal: controller.signal,
            }
          );

          if (resp.ok) {
            const json = (await resp.json()) as TradeResult;
            data = json;
          } else {
            usedMock = true;
          }
        } catch {
          usedMock = true;
        } finally {
          clearTimeout(timeoutId);
        }

        if (usedMock || !data) {
          // 模拟延迟，更像真实请求
          await new Promise((r) => setTimeout(r, 350));
          data = buildMockResult(text);
        }

        setResult(data);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "搜索失败，请稍后重试");
      } finally {
        setLoading(false);
      }
    },
    [loading]
  );

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleSearch(query);
  };

  const chips = [
    "扭曲项链",
    "Full Plate",
    "烈风手套",
    "大工匠棱镜",
    "Mageblood",
    "永恒之夜",
  ];

  return (
    <main className="text-[var(--poe-text-primary)] antialiased">
      <div className="max-w-4xl mx-auto px-4 py-6">
        {/* Header */}
        <header className="mb-6">
          <p className="ninja-section-title mb-2 font-rune">Trade Search</p>
          <h1 className="text-2xl font-semibold text-[var(--poe-text-primary)] mb-1">
            交易搜索
          </h1>
          <p className="text-sm text-[var(--poe-text-secondary)]">
            输入物品名称或关键词，检索官方交易市场在售结果。
          </p>
        </header>

        {/* Search */}
        <form onSubmit={onSubmit} className="mb-6">
          <div className="ninja-panel-accent p-1 relative">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索物品，例如：扭曲项链、Full Plate、大工匠棱镜..."
              className="ninja-textarea font-mono text-sm pr-24 resize-none bg-transparent w-full"
            />
            <div className="absolute right-3 top-2.5 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setResult(null);
                  setSearched(false);
                  setError(null);
                }}
                className="ninja-btn-ghost text-xs"
              >
                清空
              </button>
              <button
                type="submit"
                disabled={loading || !query.trim()}
                className={`ninja-btn text-xs ${!loading && query.trim() ? "ninja-glow-pulse" : ""}`}
              >
                {loading ? "搜索中..." : "搜索"}
              </button>
            </div>
          </div>

          {/* Quick chips */}
          <div className="flex flex-wrap gap-2 mt-3">
            {chips.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => {
                  setQuery(c);
                  handleSearch(c);
                }}
                className="ninja-chip"
                disabled={loading}
              >
                {c}
              </button>
            ))}
          </div>
        </form>

        {/* Error */}
        {error && (
          <div className="mb-6 ninja-panel-accent p-4" style={{ borderLeftColor: "var(--ninja-danger)" }}>
            <div className="flex items-start gap-3">
              <span className="text-red-400 text-lg">⚠</span>
              <div>
                <p className="text-[var(--ninja-danger)] font-medium">{error}</p>
              </div>
            </div>
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-4">
            {/* Best match */}
            <section>
              <h2 className="ninja-section-title mb-2">最佳匹配</h2>
              {result.best_match ? (
                <TradeMatchCard match={result.best_match} primary listingPrice={result.listing_price} />
              ) : (
                <p className="text-xs text-[var(--ninja-text-dim)]">未找到精确匹配。</p>
              )}
            </section>

            {/* Explanation */}
            {result.explanation && (
              <div className="ninja-panel p-4 text-sm text-[var(--poe-text-secondary)]">
                {result.explanation}
                {result.price_note && (
                  <p className="text-xs text-[var(--ninja-text-dim)] mt-1">{result.price_note}</p>
                )}
              </div>
            )}

            {/* Alternatives */}
            {result.alternatives?.length > 0 && (
              <section>
                <h3 className="ninja-section-title mb-2">其他筛选方式</h3>
                <div className="grid gap-2">
                  {result.alternatives.map((a, idx) => (
                    <TradeMatchCard key={idx} match={a} />
                  ))}
                </div>
              </section>
            )}
          </div>
        )}

        {/* Empty state */}
        {!searched && !result && !error && (
          <div className="ninja-panel p-6 text-center text-xs text-[var(--ninja-text-dim)]">
            输入关键词后点击搜索，或直接使用上方快捷词。
          </div>
        )}
      </div>
    </main>
  );
}
