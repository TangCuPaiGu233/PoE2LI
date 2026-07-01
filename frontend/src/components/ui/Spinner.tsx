/**
 * Spinner — animated loading spinner with configurable size and color.
 *
 * @example
 * ```tsx
 * <Spinner size="md" color="gold" />
 * <Spinner size="sm" />
 * <Spinner size="lg" className="my-custom-spinner" />
 * ```
 */
"use client";

import * as React from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Types ─────────────────────────────────────────────────────────────

export type SpinnerSize = "xs" | "sm" | "md" | "lg" | "xl";
export type SpinnerColor = "gold" | "white" | "dim" | "danger" | "success";

// ── Size Map ──────────────────────────────────────────────────────────

const SIZE_MAP: Record<SpinnerSize, string> = {
  xs: "w-3 h-3 border-[1.5px]",
  sm: "w-4 h-4 border-2",
  md: "w-6 h-6 border-2",
  lg: "w-8 h-8 border-[2.5px]",
  xl: "w-12 h-12 border-[3px]",
};

// ── Color Map ─────────────────────────────────────────────────────────

const COLOR_MAP: Record<SpinnerColor, string> = {
  gold: "border-[var(--poe-gold,#d4a94b)] border-t-[var(--poe-gold-bright,#f3cc6e)]",
  white: "border-[var(--poe-text-primary,#ede6d6)] border-t-white",
  dim: "border-[var(--poe-text-dim,#7a7060)] border-t-[var(--poe-text-secondary,#bfb59f)]",
  danger: "border-[var(--ninja-danger,#ef4444)] border-t-red-400",
  success: "border-[#34d399] border-t-emerald-400",
};

// ── Props ─────────────────────────────────────────────────────────────

export interface SpinnerProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: SpinnerSize;
  color?: SpinnerColor;
  label?: string;
}

// ── Component ─────────────────────────────────────────────────────────

/**
 * Spinner — A circular loading indicator with dark-fantasy styling.
 */
export const Spinner: React.FC<SpinnerProps> = ({
  size = "md",
  color = "gold",
  label,
  className,
  ...props
}) => {
  return (
    <div className={cn("inline-flex flex-col items-center gap-2", className)} {...props}>
      <div
        className={cn(
          "rounded-full animate-spin",
          "border-solid border-transparent",
          SIZE_MAP[size],
          COLOR_MAP[color],
        )}
        role="status"
        aria-label={label || "Loading"}
      />
      {label && (
        <span className="text-xs font-medium text-[var(--poe-text-dim,#7a7060)] tracking-wide">
          {label}
        </span>
      )}
    </div>
  );
};
