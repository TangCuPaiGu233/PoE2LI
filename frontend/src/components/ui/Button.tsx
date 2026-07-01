"use client";

import * as React from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { colors, fontSizes, fontWeights, borderRadius, shadows, spacing } from "./tokens";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Variant & Size Types ─────────────────────────────────────────────

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

// ── Variant Styles ───────────────────────────────────────────────────

const VARIANTS: Record<ButtonVariant, string> = {
  primary: cn(
    "bg-gradient-to-b from-[rgba(255,240,210,0.96)] to-[rgba(200,164,97,0.96)]",
    "text-[#1a1210] border border-[rgba(200,164,97,0.55)]",
    "shadow-[0_0_26px_rgba(200,164,97,0.35),0_0_70px_rgba(120,80,170,0.10),inset_0_1px_0_rgba(255,255,255,0.4)]",
    "hover:shadow-[0_0_34px_rgba(200,164,97,0.5),0_0_90px_rgba(120,80,170,0.16),inset_0_1px_0_rgba(255,255,255,0.45)]",
  ),
  secondary: cn(
    "bg-[rgba(212,169,75,0.12)] text-[var(--poe-gold,#d4a94b)] border border-[rgba(212,169,75,0.35)]",
    "hover:bg-[rgba(212,169,75,0.2)] hover:shadow-[0_0_24px_rgba(200,164,97,0.28)]",
  ),
  ghost: cn(
    "bg-transparent text-[var(--poe-text-secondary,#bfb59f)] border border-transparent",
    "hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--poe-text-primary,#ede6d6)] hover:border-[rgba(201,169,110,0.18)]",
  ),
  danger: cn(
    "bg-[rgba(239,68,68,0.12)] text-[var(--ninja-danger,#ef4444)] border border-[rgba(239,68,68,0.4)]",
    "hover:bg-[rgba(239,68,68,0.2)] hover:shadow-[0_0_20px_rgba(239,68,68,0.25)]",
  ),
};

// ── Size Styles ──────────────────────────────────────────────────────

const SIZES: Record<ButtonSize, string> = {
  sm: cn("text-xs px-2.5 py-1.5", "gap-1.5"),
  md: cn("text-sm px-4 py-2", "gap-2"),
  lg: cn("text-base px-6 py-3", "gap-2.5"),
};

// ── Props ────────────────────────────────────────────────────────────

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  disabled?: boolean;
  children?: React.ReactNode;
  icon?: React.ReactNode;
}

// ── Component ────────────────────────────────────────────────────────

/**
 * Button — versatile button supporting multiple variants, sizes, and a loading state.
 *
 * @example
 * ```tsx
 * <Button variant="primary" size="lg" loading>Submit</Button>
 * <Button variant="ghost" onClick={handleClick}>Cancel</Button>
 * <Button variant="danger" icon={<TrashIcon />}>Delete</Button>
 * ```
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", loading = false, disabled, icon, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center font-bold tracking-wide rounded-lg",
          "transition-all duration-200 cursor-pointer select-none",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--poe-gold)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--poe-void-deep)]",
          VARIANTS[variant],
          SIZES[size],
          loading && "pointer-events-none",
          className,
        )}
        disabled={disabled || loading}
        {...props}
      >
        {loading && (
          <svg
            className="animate-spin h-4 w-4"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        )}
        {!loading && icon && <span className="flex-shrink-0">{icon}</span>}
        {children && <span>{children}</span>}
      </button>
    );
  },
);

Button.displayName = "Button";
