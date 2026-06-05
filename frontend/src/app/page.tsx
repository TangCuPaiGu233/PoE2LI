"use client";

import { useState } from "react";

const API_URL = "http://localhost:8000";

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
  skillSets?: { gems: { nameSpec?: string }[] }[];
}

export default function Home() {
  const [pobCode, setPobCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BuildData | null>(null);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pobCode.trim()) return;

    setLoading(true);
    setError("");
    setResult(null);

    try {
      const res = await fetch(`${API_URL}/api/builds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pob_code: pobCode.trim() }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to decode");
      }

      const data = await res.json();

      // Fetch full build with homework
      const fullRes = await fetch(`${API_URL}/api/builds/${data.id}`);
      const fullData = await fullRes.json();
      setResult(fullData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100">
      <div className="max-w-4xl mx-auto px-4 py-12">
        {/* Header */}
        <div className="text-center mb-10">
          <h1 className="text-4xl font-bold mb-2">
            流放漓 <span className="text-amber-400">PoE2LI</span>
          </h1>
          <p className="text-gray-400">粘贴 PoB 分享码，获取 AI 生成的构建攻略</p>
        </div>

        {/* Input */}
        <form onSubmit={handleSubmit} className="mb-8">
          <div className="flex gap-3">
            <input
              type="text"
              value={pobCode}
              onChange={(e) => setPobCode(e.target.value)}
              placeholder="粘贴 PoB 分享码 (eN...)"
              className="flex-1 px-4 py-3 bg-gray-900 border border-gray-700 rounded-lg focus:outline-none focus:border-amber-500 text-gray-100 placeholder-gray-500"
            />
            <button
              type="submit"
              disabled={loading || !pobCode.trim()}
              className="px-6 py-3 bg-amber-500 text-gray-900 font-semibold rounded-lg hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "解析中..." : "生成攻略"}
            </button>
          </div>
        </form>

        {/* Error */}
        {error && (
          <div className="mb-6 p-4 bg-red-900/50 border border-red-700 rounded-lg text-red-200">
            {error}
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="space-y-6">
            {/* Build Info */}
            <div className="p-6 bg-gray-900 rounded-lg border border-gray-800">
              <h2 className="text-xl font-bold mb-4 text-amber-400">构建信息</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Stat label="职业" value={`${result.build.className || "?"}`} />
                <Stat label="升华" value={result.build.ascendClassName || "无"} />
                <Stat label="等级" value={result.build.level || "?"} />
                <Stat
                  label="天赋节点"
                  value={String(result.treeSpecs?.[0]?.nodes?.length || 0)}
                />
              </div>
            </div>

            {/* Key Stats */}
            <div className="p-6 bg-gray-900 rounded-lg border border-gray-800">
              <h2 className="text-xl font-bold mb-4 text-amber-400">关键属性</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Stat label="生命" value={String(result.playerStats?.Life || "?")} />
                <Stat label="魔力" value={String(result.playerStats?.Mana || "?")} />
                <Stat label="DPS" value={formatNum(result.playerStats?.TotalDPS)} />
                <Stat label="EHP" value={formatNum(result.playerStats?.TotalEHP)} />
                <Stat label="力量" value={String(result.playerStats?.Str || "?")} />
                <Stat label="敏捷" value={String(result.playerStats?.Dex || "?")} />
                <Stat label="智慧" value={String(result.playerStats?.Int || "?")} />
                <Stat
                  label="命中"
                  value={String(result.playerStats?.HitChance || "?") + "%"}
                />
              </div>
            </div>

            {/* Homework */}
            {result.homework && (
              <div className="space-y-4">
                <Section title="核心思路" content={result.homework.core_idea} />
                <Section title="核心装备" content={result.homework.core_items} />
                <Section title="预算替代" content={result.homework.budget_alternatives} />
                <Section title="天赋亮点" content={result.homework.talent_highlights} />
                <Section title="强度评估" content={result.homework.strength_review} />
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-sm text-gray-400">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

function Section({ title, content }: { title: string; content: string }) {
  return (
    <div className="p-6 bg-gray-900 rounded-lg border border-gray-800">
      <h3 className="text-lg font-bold mb-3 text-amber-400">{title}</h3>
      <div className="text-gray-300 whitespace-pre-line leading-relaxed">{content}</div>
    </div>
  );
}

function formatNum(val: number | string | undefined): string {
  if (val === undefined || val === null) return "?";
  const num = typeof val === "string" ? parseFloat(val) : val;
  if (isNaN(num)) return "?";
  if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
  if (num >= 1000) return (num / 1000).toFixed(1) + "K";
  return num.toFixed(1);
}
