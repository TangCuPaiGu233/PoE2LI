"use client";

import { useState, useEffect } from "react";

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

  // Load history on mount
  useEffect(() => {
    loadHistory();
  }, []);

  const loadHistory = async () => {
    try {
      const res = await fetch(`${API_URL}/api/builds`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
      }
    } catch {
      // Ignore history load errors
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pobCode.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);
    setLoadingStep("解码 PoB 分享码...");

    try {
      const res = await fetch(`${API_URL}/api/builds`, {
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

      // Fetch full build with homework
      const fullRes = await fetch(`${API_URL}/api/builds/${data.id}`);
      const fullData = await fullRes.json();
      setResult(fullData);
      loadHistory(); // Refresh history
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
    setLoadingStep("加载历史记录...");
    try {
      const res = await fetch(`${API_URL}/api/builds/${id}`);
      if (res.ok) {
        const data = await res.json();
        setResult(data);
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

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 24, fontFamily: "system-ui" }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
        PoE2 智能工具站「流放漓」
      </h1>
      <p style={{ color: "#666", marginBottom: 24 }}>
        粘贴 PoB 分享码，AI 自动生成中文攻略
      </p>

      {/* Input */}
      <form onSubmit={handleSubmit} style={{ marginBottom: 24 }}>
        <textarea
          value={pobCode}
          onChange={(e) => setPobCode(e.target.value)}
          placeholder="粘贴 PoB 分享码 (eNp 开头的长字符串)..."
          style={{
            width: "100%",
            height: 80,
            padding: 12,
            border: "1px solid #ddd",
            borderRadius: 8,
            fontFamily: "monospace",
            fontSize: 12,
            resize: "vertical",
          }}
        />
        <button
          type="submit"
          disabled={loading || !pobCode.trim()}
          style={{
            marginTop: 12,
            padding: "10px 24px",
            background: loading ? "#ccc" : "#0066ff",
            color: "white",
            border: "none",
            borderRadius: 8,
            cursor: loading ? "not-allowed" : "pointer",
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          {loading ? loadingStep || "处理中..." : "解析 PoB 并生成攻略"}
        </button>
      </form>

      {/* Error */}
      {error && (
        <div
          style={{
            padding: 16,
            background: "#fff0f0",
            border: "1px solid #ffcccc",
            borderRadius: 8,
            marginBottom: 24,
          }}
        >
          <strong style={{ color: "#cc0000" }}>错误：</strong> {error.message}
          {error.reason && (
            <p style={{ margin: "8px 0 0", fontSize: 13, color: "#666" }}>
              原因：{error.reason}
            </p>
          )}
        </div>
      )}

      {/* Result */}
      {result && (
        <div
          style={{
            padding: 20,
            background: "#f8f9fa",
            border: "1px solid #e0e0e0",
            borderRadius: 12,
            marginBottom: 24,
          }}
        >
          <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>
            Build 概览
          </h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
              gap: 12,
              marginBottom: 20,
            }}
          >
            <StatCard
              label="职业"
              value={`${result.build.className || "?"} / ${result.build.ascendClassName || "?"}`}
            />
            <StatCard label="等级" value={String(result.build.level || "?")} />
            <StatCard
              label="天赋节点"
              value={String(result.treeSpecs?.[0]?.nodes?.length || 0)}
            />
            <StatCard
              label="宝石"
              value={String(
                result.skillSets?.reduce((s, ss) => s + (ss.gems?.length || 0), 0) || 0
              )}
            />
            <StatCard label="物品" value={String(result.items?.length || 0)} />
            <StatCard
              label="DPS"
              value={formatNum(result.playerStats?.TotalDPS as number)}
            />
            <StatCard
              label="生命"
              value={formatNum(result.playerStats?.Life as number)}
            />
            <StatCard
              label="护甲"
              value={formatNum(result.playerStats?.Armour as number)}
            />
          </div>

          {result.homework && (
            <div>
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
                AI 攻略
              </h3>
              <HomeworkSection title="核心思路" content={result.homework.core_idea} />
              <HomeworkSection title="核心装备" content={result.homework.core_items} />
              <HomeworkSection
                title="平价替代"
                content={result.homework.budget_alternatives}
              />
              <HomeworkSection
                title="天赋亮点"
                content={result.homework.talent_highlights}
              />
              <HomeworkSection title="强度评价" content={result.homework.strength_review} />
            </div>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
            历史记录 ({history.length})
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {history.map((b) => (
              <button
                key={b.id}
                onClick={() => loadBuild(b.id)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "10px 14px",
                  background: result?.id === b.id ? "#e8f0fe" : "white",
                  border: "1px solid #e0e0e0",
                  borderRadius: 8,
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <span>
                  <strong>{b.build.className}</strong> / {b.build.ascendClassName}{" "}
                  Lv.{b.build.level}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    color: b.status === "done" ? "green" : "#999",
                  }}
                >
                  {b.status}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: "8px 12px",
        background: "white",
        border: "1px solid #e8e8e8",
        borderRadius: 6,
      }}
    >
      <div style={{ fontSize: 11, color: "#999", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function HomeworkSection({ title, content }: { title: string; content: string }) {
  if (!content) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{title}</h4>
      <p style={{ fontSize: 13, lineHeight: 1.6, color: "#333", margin: 0 }}>{content}</p>
    </div>
  );
}

function formatNum(n: number): string {
  if (!n) return "0";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toFixed(0);
}
