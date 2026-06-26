"use client";

import { useState } from "react";
import { apiUrl } from "@/lib/apiUrl";

/* ── Filter rule definitions ── */
const RULES = [
  {
    id: 1,
    title: "高价底材 · 强制显示",
    color: "#d4913f",
    desc: "从 Trade API 扫描所有白装底材，价格 >= 8E 的底材自动加入强制显示列表。遗产金色边框 + 红色星形地图标记 + 警报音。不受词缀阶级限制。",
    example: "Tribal Bow (9499c)、Full Plate (9477c)、Shortbow (496c) 等 43 个底材",
  },
  {
    id: 2,
    title: "五阶白装 · 高亮显示",
    color: "#4ae63a",
    desc: "词缀阶级 (UnidentifiedItemTier) >= 5 的白装，绿色文字 + 青色边框 + 音效 + 青色光束。这类底材有极高做装潜力。",
    example: "任何五阶 Normal 装备 — 胸甲、武器、饰品等",
  },
  {
    id: 3,
    title: "特殊做装底材 · 强制显示",
    color: "#ffc832",
    desc: "部分白装底材用于机会石点暗金等特殊做装路线，价值与物品等级无关。黄色边框 + 黄色圆形地图标记，不限 ilvl。",
    example: "Heavy Belt（机会石 → 猎手腰带）",
  },
  {
    id: 4,
    title: "ilvl >= 82 白装 · 保底显示",
    color: "#c8c8c8",
    desc: "物品等级 >= 82 的白装作为 endgame 做装底材保底显示。灰色边框，无音效。覆盖所有装备类型。",
    example: "82 级以上地图掉落的任何白装装备",
  },
  {
    id: 5,
    title: "五阶黄装 / 蓝装 · 模板规则",
    color: "#ffdc00",
    desc: "模板自带规则：词缀阶级 >= 5 的 Rare（黄装）显示黄色边框 + 黄钻石图标，Magic（蓝装）显示蓝色边框 + 蓝钻石图标。需 AreaLevel >= 65。",
    example: "五阶未鉴定黄装 — 值得点开看词缀",
  },
  {
    id: 6,
    title: "低阶低等级白装 · 隐藏",
    color: "#555",
    desc: "词缀阶级 < 5 且物品等级 < 82 的白装被隐藏。这些底材做装价值极低，减少视觉干扰。",
    example: "低等级地图掉落的普通白装",
  },
  {
    id: 7,
    title: "低价通货 · poe.ninja 实时隐藏",
    color: "#ef4444",
    desc: "从 poe.ninja 实时拉取 14 个品类的通货价格，低于 1c（混沌石）的物品自动隐藏。每次生成过滤器时刷新数据。核心通货（混沌石、崇高石、宝石匠棱镜、瓦尔宝珠、魔镜、辛格拉发辫）永不隐藏。",
    example: "护甲片(0.03c)、磨刀石(0.01c)、改造石(0.00c)、低阶精华、低阶符文等 441 个物品",
  },
];

/* ── Usage steps ── */
const STEPS = [
  {
    step: 1,
    title: "下载过滤器",
    desc: "点击下方按钮生成并下载最新的 .filter 文件。过滤器会自动从 Trade API 和 poe.ninja 拉取最新数据。",
  },
  {
    step: 2,
    title: "放入 PoE2 过滤器目录",
    desc: '将下载的 .filter 文件复制到：C:\\Users\\<用户名>\\Documents\\My Games\\Path of Exile 2\\',
  },
  {
    step: 3,
    title: "在游戏内启用",
    desc: "打开游戏 → 设置 → 界面 → 物品过滤器 → 选择下载的过滤器文件 → 确认。",
  },
  {
    step: 4,
    title: "开始刷图",
    desc: "过滤器会自动生效。高价底材会有醒目的金色光芒和警报音，五阶白装有绿色高亮，廉价物品被隐藏。",
  },
];

export default function FilterPage() {
  const [downloading, setDownloading] = useState(false);
  const [dlResult, setDlResult] = useState<{ filename: string; size: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const apiBase = apiUrl();

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    setDlResult(null);

    try {
      const dlResp = await fetch(`${apiBase}/api/filter/download`);
      if (!dlResp.ok) {
        const err = await dlResp.json().catch(() => ({}));
        throw new Error(
          (err as { detail?: string }).detail || `下载失败 (${dlResp.status})`,
        );
      }

      const blob = await dlResp.blob();
      const rawName = dlResp.headers.get("x-filter-filename") || "";
      const filename = rawName
        ? decodeURIComponent(rawName)
        : (() => {
            const cd = dlResp.headers.get("content-disposition") || "";
            const m = cd.match(/filename\*=(?:utf-8'')?([^;\n]+)/i);
            return m ? decodeURIComponent(m[1].replace(/['"]/g, "")) : "流放漓.filter";
          })();

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      setDlResult({ filename, size: blob.size });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <main>
      {/* Hero */}
      <header className="ninja-hero">
        <p className="ninja-section-title mb-3 font-rune">Item Filter</p>
        <h1 className="ninja-hero-title">AI 智能筛选器</h1>
        <div className="ninja-hero-sigil" />
        <p className="ninja-hero-sub">
          基于 Trade API 实时扫描 + poe.ninja 通货数据，自动生成 PoE2 物品过滤器
        </p>
      </header>

      {/* Download Section */}
      <section className="ninja-panel-accent p-6 mb-8 flex flex-col sm:flex-row items-start sm:items-center gap-4">
        <div className="flex-1">
          <h2 className="text-lg font-semibold mb-1 text-[var(--poe-text-primary)]">下载最新过滤器</h2>
          <p className="text-sm text-[var(--poe-text-secondary)]">
            基于 857 个白装底材 Trade API 扫描 + poe.ninja 实时通货数据，管理员定期更新。
          </p>
          {dlResult && (
            <p className="text-xs text-[var(--poe-gold)] mt-2">
              已下载 {dlResult.filename} ({(dlResult.size / 1024).toFixed(0)} KB)
            </p>
          )}
          {error && (
            <p className="text-xs text-[var(--poe-corruption)] mt-2">
              {error}
            </p>
          )}
        </div>
        <button
          className="ninja-btn whitespace-nowrap text-base py-3 px-6"
          disabled={downloading}
          onClick={handleDownload}
        >
          {downloading ? "下载中..." : "下载 .filter 文件"}
        </button>
      </section>

      {/* Rules Section */}
      <section className="mb-10">
        <h2 className="ninja-section-title mb-4">筛选规则</h2>
        <div className="grid gap-3">
          {RULES.map((rule) => (
            <div
              key={rule.id}
              className="ninja-panel p-4 relative overflow-hidden"
            >
              <div
                className="absolute left-0 top-0 bottom-0 w-[3px]"
                style={{ background: `linear-gradient(180deg, ${rule.color}, transparent)` }}
              />
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className="inline-block w-2.5 h-2.5 rounded-full"
                  style={{ background: rule.color, boxShadow: `0 0 8px ${rule.color}55` }}
                />
                <span className="font-semibold text-sm text-[var(--poe-text-primary)]">
                  {rule.id}. {rule.title}
                </span>
              </div>
              <p className="text-sm text-[var(--poe-text-secondary)] leading-relaxed">
                {rule.desc}
              </p>
              <p className="text-xs text-[var(--poe-text-dim)] mt-1.5">
                例: {rule.example}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Usage Tutorial */}
      <section className="mb-10">
        <h2 className="ninja-section-title mb-4">使用教程</h2>
        <div className="grid gap-3">
          {STEPS.map(({ step, title, desc }) => (
            <div key={step} className="ninja-panel-accent p-4 flex gap-4">
              <span className="flex-shrink-0 w-8 h-8 rounded-full bg-[var(--poe-gold)] text-[var(--poe-void-deep)] font-bold text-sm flex items-center justify-center shadow-[0_0_14px_rgba(212,169,75,0.35)]">
                {step}
              </span>
              <div>
                <h3 className="font-semibold text-sm mb-1 text-[var(--poe-text-primary)]">{title}</h3>
                <p className="text-sm text-[var(--poe-text-secondary)]">{desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Technical Details */}
      <section className="mb-10">
        <h2 className="ninja-section-title mb-4">技术细节</h2>
        <div className="ninja-panel-accent p-5 text-sm text-[var(--poe-text-secondary)] space-y-3">
          <p>
            <strong className="text-[var(--poe-gold)]">数据来源</strong>
            ：白装底材价格来自 PoE2 官方 Trade API（CN 服务器），通货价格来自 poe.ninja 实时数据。
          </p>
          <p>
            <strong className="text-[var(--poe-gold)]">更新频率</strong>
            ：底材每日 06:00 自动扫描（857 个素体），通货价格每次生成时实时拉取。也可手动触发重新生成。
          </p>
          <p>
            <strong className="text-[var(--poe-gold)]">模板基础</strong>
            ：基于 asmco 四后期过滤器模板，保留原有的五阶黄/蓝装规则、已鉴定词缀规则等。AI 规则注入在模板规则之前，利用 first-match-wins 机制优先生效。
          </p>
          <p>
            <strong className="text-[var(--poe-gold)]">防操纵机制</strong>
            ：高价底材要求至少 3 条在售listing，取中位价而非最低价，防止单条异常挂单影响判断。
          </p>
          <p>
            <strong className="text-[var(--poe-gold)]">注意事项</strong>
            ：过滤器无法修改物品名称或显示自定义文字（PoE2 限制），只能通过颜色、图标、音效来区分价值等级。
          </p>
        </div>
      </section>

      {/* File path hint */}
      <section className="mb-8">
        <div className="ninja-panel p-4 text-xs text-[var(--poe-text-dim)]">
          <p>
            过滤器文件路径:{" "}
            <code className="text-[var(--poe-gold)]">
              C:\Users\&lt;用户名&gt;\Documents\My Games\Path of Exile 2\
            </code>
          </p>
          <p className="mt-1 text-[var(--poe-text-secondary)]">
            游戏内设置路径: 设置 → 界面 → 物品过滤器 → 选择文件
          </p>
        </div>
      </section>
    </main>
  );
}
