"use client";

import { useState, useEffect, useCallback } from "react";
import { addLocalBuildHistory, getLocalBuildHistory, toHistorySummary } from "@/lib/buildHistory";

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

export default function Home() {
  const [pobCode, setPobCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState("");
  const [result, setResult] = useState<BuildData | null>(null);
  const [error, setError] = useState<{ message: string; reason?: string } | null>(null);
  const [history, setHistory] = useState<BuildSummary[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [pobValid, setPobValid] = useState<boolean | null>(null);
  
  const loadHistory = useCallback(() => {
    setHistory(getLocalBuildHistory().map(toHistorySummary));
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
    const isWegame = /^https?:\/\/(?:www\.)?wegame\.com\.cn\/helper\/poe2/i.test(trimmed);
    const isBase64 = trimmed.startsWith("eN") && trimmed.length > 100;
    
    // Also allow raw base64 that might start with eN or have some spaces
    const isBase64Relaxed = trimmed.replace(/\s/g, '').startsWith("eN") && trimmed.length > 100;
    
    setPobValid(isPobbin || isPoeNinja || isWegame || isBase64 || isBase64Relaxed);
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
      addLocalBuildHistory({ id: data.id, status: data.status || "pending", build: data.build || {}, savedAt: new Date().toISOString() });
      loadHistory();
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
          addLocalBuildHistory({ id: buildId, status: "done", build: fullData.build || {}, savedAt: new Date().toISOString() });
          loadHistory();
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
        throw { message: "AI 生成超时，请稍后在本机历史中查看" };
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

  const copyShareLink = () => {
    if (result?.id) {
      const url = `${window.location.origin}?build=${result.id}`;
      navigator.clipboard.writeText(url);
    }
  };

  const stats = result?.playerStats || {};
  const gems = result?.skillSets?.flatMap((s) => s.gems?.filter((g) => g.nameSpec) || []) || [];

  return (
    <div>
        <header className="ninja-hero">
          <p className="ninja-section-title mb-3 font-rune">Build Analyzer</p>
          <h1 className="ninja-hero-title">PoB 构建分析</h1>
          <div className="ninja-hero-sigil" />
          <p className="ninja-hero-sub">
            粘贴 PoB 分享码或 poe.ninja 角色链接，自动解析装备并生成中文攻略
          </p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-8">
          {/* Main */}
          <div>
            {/* Input */}
            <form onSubmit={handleSubmit} className="mb-6">
              <div className="ninja-panel-accent p-1 relative">
                <textarea
                  value={pobCode}
                  onChange={(e) => setPobCode(e.target.value)}
                  placeholder="粘贴 PoB 分享码 (eNp...) 或 pobb.in / poe.ninja 链接..."
                  rows={3}
                  className="ninja-textarea font-mono text-sm pr-24 resize-none"
                />
                <div className="absolute right-3 top-3 flex gap-2">
                  <button
                    type="button"
                    onClick={handlePaste}
                    className="ninja-btn-ghost"
                  >
                    粘贴
                  </button>
                </div>
              </div>

              {/* Validation feedback */}
              {pobValid === false && pobCode.length > 10 && (
                <p className="mt-2 text-xs text-[var(--poe-corruption)]">
                  支持 PoB 分享码 (eN 开头) 或 https://pobb.in/ 或 https://poe.ninja/ 链接
                </p>
              )}
              {pobValid === true && (
                <p className="mt-2 text-xs text-[var(--poe-gold)]">✓ 格式正确</p>
              )}

              <button
                type="submit"
                disabled={loading || !pobValid}
                className={`ninja-btn mt-3 w-full py-3 ${!loading && pobValid ? 'ninja-glow-pulse' : ''}`}
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
              <div className="mb-6 ninja-panel-accent p-4" style={{ borderLeftColor: "var(--ninja-danger)" }}>
                <div className="flex items-start gap-3">
                  <span className="text-red-400 text-lg">⚠</span>
                  <div>
                    <p className="text-[var(--ninja-danger)] font-medium">{error.message}</p>
                    {error.reason && (
                      <p className="text-[var(--ninja-text-dim)] text-xs mt-1">错误类型: {error.reason}</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Result */}
            {result && (
              <div className="space-y-4">
                {/* Build Info Card */}
                <div className="ninja-panel-accent p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-bold font-rune text-[var(--poe-gold-bright)]">
                      {result.build.className} / {result.build.ascendClassName}
                    </h2>
                    <span className="ninja-badge">Lv.{result.build.level}</span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <Stat label="生命" value={formatNum(stats.Life as number)} color="text-red-400" />
                    <Stat label="魔力" value={formatNum(stats.Mana as number)} color="text-blue-400" />
                    <Stat label="DPS" value={formatNum(stats.TotalDPS as number)} color="text-[var(--ninja-accent)]" />
                    <Stat label="护甲" value={formatNum(stats.Armour as number)} color="text-[var(--ninja-text-muted)]" />
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
                  <div className="ninja-panel p-5">
                    <h3 className="ninja-section-title mb-3">技能宝石</h3>
                    <div className="flex flex-wrap gap-2">
                      {gems.map((g, i) => (
                        <span
                          key={i}
                          className="px-2.5 py-1 bg-[rgba(201,169,110,0.08)] border border-[rgba(201,169,110,0.35)] rounded text-xs text-[var(--poe-rune)]"
                          style={{ boxShadow: 'inset 0 0 12px rgba(212,169,75,0.08)' }}
                        >
                          {g.nameSpec}
                          <span className="text-[var(--poe-text-dim)] ml-1">Lv{g.level}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Homework */}
                {result.homework && (
                  <div className="ninja-panel p-5">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="ninja-section-title">🤖 AI 攻略</h3>
                      <div className="flex gap-3">
                        <a href="/chat" className="ninja-link text-xs">
                          🔍 在对话里搜装备
                        </a>
                        <button onClick={copyShareLink} className="ninja-btn-ghost text-xs">
                          复制链接
                        </button>
                      </div>
                    </div>
                    <div className="space-y-3">
                      <CollapsibleBlock title="💡 核心思路" content={result.homework.core_idea} defaultOpen />
                      <CollapsibleBlock title="🛡 核心装备" content={result.homework.core_items} />
                      <CollapsibleBlock title="💰 平价替代" content={result.homework.budget_alternatives} />
                      <CollapsibleBlock title="🌳 天赋亮点" content={result.homework.talent_highlights} />
                      <CollapsibleBlock title="📊 强度评价" content={result.homework.strength_review} />
                    </div>
                  </div>
                )}

                <a
                  href="/chat"
                  className="block ninja-panel-accent p-4 text-center hover:bg-[var(--ninja-panel-hover)] transition-colors"
                >
                  <span className="text-[var(--ninja-accent)] text-sm font-medium">在 AI 问答中深入讨论这个 Build</span>
                  <p className="text-[var(--ninja-text-dim)] text-xs mt-1">多轮对话、装备推荐、BD 造价</p>
                </a>
              </div>
            )}
          </div>

          {/* Sidebar - History */}
          <div className="lg:sticky lg:top-24 lg:self-start">
            <div className="ninja-panel p-4">
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="w-full flex items-center justify-between ninja-section-title mb-3"
              >
                <span>本机历史 ({history.length})</span>
                <span className="text-xs">{showHistory ? "▲" : "▼"}</span>
              </button>

              {showHistory && (
                <p className="text-[10px] text-[var(--ninja-text-dim)] mb-2">仅保存在当前浏览器，不会看到其他访客的记录</p>
              )}

              {showHistory && (
                <div className="space-y-2 max-h-[60vh] overflow-y-auto">
                  {history.length === 0 ? (
                    <p className="text-xs text-[var(--ninja-text-dim)] text-center py-4">暂无记录</p>
                  ) : (
                    history.map((b) => (
                      <button
                        key={b.id}
                        onClick={() => loadBuild(b.id)}
                        className={`w-full p-3 rounded-lg text-left text-xs transition-all ${
                          result?.id === b.id
                            ? "bg-[rgba(212,169,75,0.12)] border-[rgba(212,169,75,0.4)] shadow-[0_0_18px_rgba(212,169,75,0.18)]"
                            : "bg-[var(--poe-surface-2)] border-[var(--ninja-border)] hover:border-[rgba(201,169,110,0.45)] hover:shadow-[0_0_18px_rgba(212,169,75,0.12)]"
                        }`}
                      >
                        <div className="font-medium text-[var(--ninja-text)]">
                          {b.build.className}{" "}
                          <span className="text-[var(--ninja-text-dim)]">Lv.{b.build.level}</span>
                        </div>
                        <div className="text-[var(--ninja-text-muted)] mt-0.5">
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
  );
}

function Stat({ label, value, color = "text-white" }: { label: string; value: string; color?: string }) {
  return (
    <div className="ninja-stat">
      <div className="ninja-stat-label">{label}</div>
      <div className={`ninja-stat-value ${color}`}>{value}</div>
    </div>
  );
}

function CollapsibleBlock({ title, content, defaultOpen = false }: { title: string; content: string; defaultOpen?: boolean }) {
  if (!content) return null;
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ninja-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-3 text-left hover:bg-[rgba(201,169,110,0.06)] transition-colors"
      >
        <span className="text-xs font-semibold text-[var(--poe-gold)]">{title}</span>
        <span className="text-[var(--poe-text-dim)] text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          <p className="text-sm text-[var(--poe-text-secondary)] leading-relaxed whitespace-pre-line pt-2">{content}</p>
        </div>
      )}
    </div>
  );
}

function formatNum(n: number): string {
  if (!n) return "0";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toFixed(0);
}
