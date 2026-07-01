/**
 * Card — generic card container with title, variant support, and hover effects.
 *
 * @example
 * ```tsx
 * <Card title="Player Profile">
 *   <div>Level 82</div>
 * </Card>
 * <Card variant="accent" title="Rare Item">...</Card>
 * ```
 */
"use client";

import * as React from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { borderRadius, shadows } from "./tokens";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Variant Types ─────────────────────────────────────────────────────

export type CardVariant = "default" | "accent" | "subtle";

// ── Variant Styles ───────────────────────────────────────────────────

const VARIANT_STYLES: Record<CardVariant, string> = {
  default: cn(
    "bg-gradient-to-b from-[var(--poe-surface-2,#18151f)] to-[var(--poe-surface-1,#12101a)]",
    "border border-[rgba(74,60,90,0.55)]",
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.03),0_18px_40px_rgba(0,0,0,0.45)]",
    "hover:border-[rgba(201,169,110,0.25)]",
  ),
  accent: cn(
    "bg-gradient-to-b from-[var(--poe-surface-2,#18151f)] to-[var(--poe-surface-1,#12101a)]",
    "border border-[rgba(212,169,75,0.32)]",
    "shadow-[0_0_28px_rgba(212,169,75,0.18),0_0_80px_rgba(120,80,170,0.08),inset_0_1px_0_rgba(255,255,255,0.05),0_18px_40px_rgba(0,0,0,0.55)]",
    "hover:border-[rgba(212,169,75,0.5)]",
  ),
  subtle: cn(
    "bg-[rgba(0,0,0,0.22)]",
    "border border-[rgba(74,60,90,0.55)]",
    "hover:border-[rgba(201,169,110,0.2)]",
  ),
};

// ── Props ─────────────────────────────────────────────────────────────

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  title?: React.ReactNode;
  titleAlign?: "left" | "center" | "right";
  padding?: "none" | "sm" | "md" | "lg";
  children?: React.ReactNode;
}

// ── Padding Styles ───────────────────────────────────────────────────

const PADDING_MAP: Record<string, string> = {
  none: "p-0",
  sm: "p-3",
  md: "p-5",
  lg: "p-8",
};

// ── Component ─────────────────────────────────────────────────────────

/**
 * Card — A versatile container component with dark-fantasy styling.
 */
export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  (
    {
      className,
      variant = "default",
      title,
      titleAlign = "left",
      padding = "md",
      children,
      ...props
    },
    ref,
  ) => {
    const titleAlignMap: Record<string, string> = {
      left: "text-left",
      center: "text-center",
      right: "text-right",
    };

    return (
      <div
        ref={ref}
        className={cn(
          "rounded-xl transition-all duration-200",
          VARIANT_STYLES[variant],
          PADDING_MAP[padding],
          className,
        )}
        {...props}
      >
        {title && (
          <div
            className={cn(
              "mb-3",
              padding === "none" && "mb-0",
              titleAlignMap[titleAlign],
            )}
          >
            <h3 className="font-rune text-sm font-bold tracking-wider text-[var(--poe-gold,#d4a94b)]">
              {title}
            </h3>
          </div>
        )}
        {children}
      </div>
    );
  },
);

Card.displayName = "Card";
