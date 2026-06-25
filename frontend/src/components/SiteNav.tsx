"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "PoB 解析", desc: "导入 & 攻略" },
  { href: "/chat", label: "AI 问答", desc: "百科 & 市集" },
  { href: "/filter", label: "筛选器", desc: "智能过滤" },
];

export default function SiteNav() {
  const pathname = usePathname();

  return (
    <header className="ninja-nav-wrap">
      <nav className="ninja-nav">
        <Link href="/" className="ninja-nav-brand">
          <span className="ninja-nav-icon" aria-hidden>漓</span>
          <span className="ninja-nav-brand-text font-rune" style={{ fontSize: "0.95rem" }}>流放漓</span>
        </Link>

        <div className="ninja-nav-tabs" role="tablist" aria-label="主导航">
          {LINKS.map(({ href, label, desc }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                role="tab"
                aria-selected={active}
                className={`ninja-nav-tab${active ? " active" : ""}`}
              >
                <span className="ninja-nav-tab-label">{label}</span>
                <span className="ninja-nav-tab-desc">{desc}</span>
              </Link>
            );
          })}
        </div>

        <div className="ninja-nav-right">
          <span className="ninja-badge">PoE 2</span>
        </div>
      </nav>
    </header>
  );
}
