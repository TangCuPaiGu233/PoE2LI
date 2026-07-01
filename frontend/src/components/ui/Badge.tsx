/**
 * Badge — small status/label badge with variant and size options.
 *
 * @example
 * ```tsx
 * <Badge variant="gold">Legendary</Badge>
 * <Badge variant="corruption">Corrupted</Badge>
 * <Badge variant="verdigris" size="sm">New</Badge>
 * ```
 */
"use client";

import * as React from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { borderRadius, colors } from "./tokens";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Types ─────────────────────────────────────────────────────────────

export type BadgeVariant =
  | "gold"
  | "corruption"
  | "verdigris"
  | "rune"
  | "danger"
  | "success"
  | "neutral"
  | "dim";

export type BadgeSize = "xs" | "sm" | "md";

// ── Variant Styles ────────────────────────────────────────────────────

interface BadgeVariantStyle {
  bg: string;
  border: string;
  text: string;
  shadow?: string;
}

const VARIANT_STYLES: Record<BadgeVariant, BadgeVariantStyle> = {
  gold: {
    bg: "bg-[rgba(212,169,75,0.10)]",
    border: "border-[rgba(212,169,75,0.35)]",
    text: "text-[var(--poe-gold,#d4a94b)]",
    shadow: "shadow-[0_0_20px_rgba(200,164,97,0.18)]",
  },
  corruption: {
    bg: "bg-[rgba(122,31,31,0.15)]",
    border: "border-[rgba(154,38,38,0.4)]",
    text: "text-[#c44]",
    shadow: "shadow-[0_0_16px_rgba(154,38,38,0.15)]",
  },
  verdigris: {
    bg: "bg-[rgba(61,90,84,0.15)]",
    border: "border-[rgba(61,90,84,0.5)]",
    text: "text-[#5a9e8f]",
    shadow: "shadow-[0_0_16px_rgba(61,90,84,0.12)]",
  },
  rune: {
    bg: "bg-[rgba(201,169,110,0.08)]",
    border: "border-[rgba(201,169,110,0.3)]",
    text: "text-[var(--poe-rune,#c9a96e)]",
  },
  danger: {
    bg: "bg-[rgba(239,68,68,0.10)]",
    border: "border-[rgba(239,68,68,0.35)]",
    text: "text-[var(--ninja-danger,#ef4444)]",
  },
  success: {
    bg: "bg-[rgba(52,211,153,0.10)]",
    border: "border-[rgba(52,211,153,0.35)]",
    text: "text-[#34d399]",
  },
  neutral: {
    bg: "bg-[rgba(255,255,255,0.04)]",
    border: "border-[rgba(74,60,90,0.4)]",
    text: "text-[var(--poe-text-secondary,#bfb59f)]",
  },
  dim: {
    bg: "bg-[rgba(122,112,96,0.06)]",
    border: "border-[rgba(122,112,96,0.25)]",
    text: "text-[var(--poe-text-dim,#7a7060)]",
  },
};

// ── Size Map ──────────────────────────────────────────────────────────

const SIZE_MAP: Record<BadgeSize, string> = {
  xs: cn("text-[0.62rem] px-1.5 py-0.5", "gap-1"),
  sm: cn("text-xs px-2 py-0.5", "gap-1.5"),
  md: cn("text-sm px-2.5 py-1", "gap-2"),
};

// ── Props ─────────────────────────────────────────────────────────────

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
  children?: React.ReactNode;
}

// ── Component ─────────────────────────────────────────────────────────

/**
 * Badge — A compact status badge with dark-fantasy theming.
 */
export const Badge: React.FC<BadgeProps> = ({
  variant = "neutral",
  size = "sm",
  dot = false,
  className,
  children,
  ...props
}) => {
  const style = VARIANT_STYLES[variant];

  return (
    <span
      className={cn(
        "inline-flex items-center font-bold tracking-wide rounded-full",
        "border transition-all duration-150",
        style.bg,
        style.border,
        style.text,
        style.shadow || "",
        SIZE_MAP[size],
        className,
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full flex-shrink-0",
            variant === "gold" && "bg-[var(--poe-gold,#d4a94b)]",
            variant === "corruption" && "bg-[#c44]",
            variant === "verdigris" && "bg-[#5a9e8f]",
            variant === "rune" && "bg-[var(--poe-rune,#c9a96e)]",
            variant === "danger" && "bg-[var(--ninja-danger,#ef4444)]",
            variant === "success" && "bg-[#34d399]",
            variant === "neutral" && "bg-[var(--poe-text-secondary,#bfb59f)]",
            variant === "dim" && "bg-[var(--poe-text-dim,#7a7060)]",
          )}
        />
      )}
      {children}
    </span>
  );
};
