/**
 * Input — text input with label, error state, and prefix/suffix slots.
 *
 * @example
 * ```tsx
 * <Input label="Character Name" placeholder="Enter name..." />
 * <Input label="Search" suffix={<SearchIcon />} error="Name is required" />
 * <Input label="Gold" prefix="🪙" type="number" />
 * ```
 */
"use client";

import * as React from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Props ─────────────────────────────────────────────────────────────

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'prefix'> {
  label?: React.ReactNode;
  error?: string;
  helper?: string;
  prefix?: React.ReactNode;
  suffix?: React.ReactNode;
}

// ── Component ─────────────────────────────────────────────────────────

/**
 * Input — A styled text input supporting labels, validation, and icon slots.
 */
export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    {
      className,
      label,
      error,
      helper,
      prefix,
      suffix,
      id,
      disabled,
      ...props
    },
    ref,
  ) => {
    const inputId = id || `input-${Math.random().toString(36).slice(2, 9)}`;

    return (
      <div className={cn("w-full", className)}>
        {label && (
          <label
            htmlFor={inputId}
            className={cn(
              "block mb-1.5 text-sm font-semibold tracking-wide",
              "text-[var(--poe-text-secondary,#bfb59f)]",
              disabled && "opacity-50",
            )}
          >
            {label}
          </label>
        )}

        <div
          className={cn(
            "relative flex items-center",
            "rounded-lg",
            "border border-[rgba(74,60,90,0.65)]",
            "bg-[rgba(0,0,0,0.25)]",
            error
              ? "border-[rgba(239,68,68,0.6)] shadow-[0_0_0_3px_rgba(239,68,68,0.1)]"
              : "hover:border-[rgba(212,169,75,0.4)]",
            "focus-within:border-[rgba(212,169,75,0.55)]",
            "focus-within:shadow-[0_0_0_3px_rgba(212,169,75,0.12),0_0_28px_rgba(212,169,75,0.14),0_0_70px_rgba(120,80,170,0.08)]",
            disabled && "opacity-50 cursor-not-allowed",
          )}
        >
          {prefix && (
            <span className="pl-3 pr-1 text-[var(--poe-gold,#d4a94b)] flex-shrink-0">
              {prefix}
            </span>
          )}

          <input
            ref={ref}
            id={inputId}
            disabled={disabled}
            className={cn(
              "w-full bg-transparent px-3 py-2 text-sm text-[var(--poe-text-primary,#ede6d6)]",
              "placeholder:text-[var(--poe-text-dim,#7a7060)]",
              "outline-none",
              prefix ? "pl-1" : "",
              suffix ? "pr-1" : "",
            )}
            {...props}
          />

          {suffix && (
            <span className="pl-1 pr-3 text-[var(--poe-gold,#d4a94b)] flex-shrink-0">
              {suffix}
            </span>
          )}
        </div>

        {error && (
          <p className="mt-1 text-xs font-medium text-[var(--ninja-danger,#ef4444)]">
            {error}
          </p>
        )}
        {helper && !error && (
          <p className="mt-1 text-xs text-[var(--poe-text-dim,#7a7060)]">
            {helper}
          </p>
        )}
      </div>
    );
  },
);

Input.displayName = "Input";
