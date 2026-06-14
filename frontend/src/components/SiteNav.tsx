"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "PoB 解析" },
  { href: "/chat", label: "AI 问答" },
];

export default function SiteNav() {
  const pathname = usePathname();

  return (
    <nav className="ninja-nav">
      <Link href="/" className="ninja-nav-brand">
        <span className="ninja-nav-icon" aria-hidden>
          漓
        </span>
        <span>流放漓</span>
        <span className="hidden sm:inline text-xs font-normal text-[var(--ninja-text-dim)] ml-0.5">
          PoE2LI
        </span>
      </Link>

      <div className="ninja-nav-links">
        {LINKS.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={`ninja-nav-link${pathname === href ? " active" : ""}`}
          >
            {label}
          </Link>
        ))}
      </div>

      <span className="ninja-badge hidden sm:inline">PoE 2</span>
    </nav>
  );
}
