/**
 * Select — dropdown select with label, error state, and custom styling.
 *
 * @example
 * ```tsx
 * <Select label="Class" value={value} onChange={setValue}>
 *   <option value="">Select class...</option>
 *   <option value="marauder">Marauder</option>
 *   <option value="ranger">Ranger</option>
 * </Select>
 * <Select label="Region" error="Please select a region">...</Select>
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

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  label?: React.ReactNode;
  error?: string;
  helper?: string;
  placeholder?: string;
  children?: React.ReactNode;
}

// ── Component ─────────────────────────────────────────────────────────

/**
 * Select — A styled dropdown select with label, validation, and arrow icon.
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      className,
      label,
      error,
      helper,
      placeholder,
      children,
      id,
      disabled,
      ...props
    },
    ref,
  ) => {
    const selectId = id || `select-${Math.random().toString(36).slice(2, 9)}`;

    return (
      <div className={cn("w-full", className)}>
        {label && (
          <label
            htmlFor={selectId}
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
            "relative",
            "rounded-lg",
            "border border-[rgba(74,60,90,0.65)]",
            "bg-[rgba(0,0,0,0.25)]",
            error
              ? "border-[rgba(239,68,68,0.6)] shadow-[0_0_0_3px_rgba(239,68,68,0.1)]"
              : "hover:border-[rgba(212,169,75,0.4)]",
            "focus-within:border-[rgba(212,169,75,0.55)]",
            "focus-within:shadow-[0_0_0_3px_rgba(212,169,75,0.12),0_0_28px_rgba(212,169,75,0.14)]",
            disabled && "opacity-50 cursor-not-allowed",
          )}
        >
          <select
            ref={ref}
            id={selectId}
            disabled={disabled}
            className={cn(
              "w-full appearance-none bg-transparent px-3 py-2 text-sm",
              "text-[var(--poe-text-primary,#ede6d6)]",
              "outline-none cursor-pointer",
              disabled && "cursor-not-allowed",
            )}
            {...props}
          >
            {placeholder && (
              <option value="" disabled className="text-[var(--poe-text-dim)]">
                {placeholder}
              </option>
            )}
            {children}
          </select>

          {/* Custom arrow */}
          <span className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--poe-gold,#d4a94b)]">
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </span>
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

Select.displayName = "Select";
