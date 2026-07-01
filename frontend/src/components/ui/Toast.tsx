/**
 * Toast — lightweight notification component supporting success/error/info/warning variants.
 *
 * @example
 * ```tsx
 * <Toast open message="Item equipped!" variant="success" onClose={() => setOpen(false)} />
 * <Toast open message="Failed to login" variant="error" onClose={() => setOpen(false)} />
 * ```
 */
"use client";

import * as React from "react";
import { useEffect, useRef, useCallback } from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { zIndex, colors, transitions } from "./tokens";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Types ─────────────────────────────────────────────────────────────

export type ToastVariant = "success" | "error" | "info" | "warning";

interface ToastVariantStyle {
  bg: string;
  border: string;
  iconBg: string;
  textColor: string;
}

const VARIANT_STYLES: Record<ToastVariant, ToastVariantStyle> = {
  success: {
    bg: "bg-[rgba(16,11,28,0.95)]",
    border: "border-[rgba(52,211,153,0.4)]",
    iconBg: "bg-[rgba(52,211,153,0.15)]",
    textColor: "text-[#34d399]",
  },
  error: {
    bg: "bg-[rgba(11,4,4,0.95)]",
    border: "border-[rgba(239,68,68,0.5)]",
    iconBg: "bg-[rgba(239,68,68,0.15)]",
    textColor: "text-[#ef4444]",
  },
  info: {
    bg: "bg-[rgba(10,12,28,0.95)]",
    border: "border-[rgba(96,165,250,0.4)]",
    iconBg: "bg-[rgba(96,165,250,0.15)]",
    textColor: "text-[#60a5fa]",
  },
  warning: {
    bg: "bg-[rgba(20,14,4,0.95)]",
    border: "border-[rgba(245,158,11,0.4)]",
    iconBg: "bg-[rgba(245,158,11,0.15)]",
    textColor: "text-[#f59e0b]",
  },
};

const ICONS: Record<ToastVariant, React.ReactNode> = {
  success: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  ),
  error: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  ),
  info: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M12 2a10 10 0 100 20 10 10 0 000-20z" />
    </svg>
  ),
  warning: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86l-8.58 14.86A1 1 0 002.66 20h18.68a1 1 0 00.95-1.28L11.71 3.86a1 1 0 00-1.42 0z" />
    </svg>
  ),
};

// ── Props ─────────────────────────────────────────────────────────────

export interface ToastProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'variant'> {
  variant?: ToastVariant;
  message: React.ReactNode;
  open?: boolean;
  duration?: number;
  onClose?: () => void;
  showClose?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────

/**
 * Toast — A non-blocking notification toast. Auto-dismisses after `duration` ms.
 */
export const Toast: React.FC<ToastProps> = ({
  variant = "info",
  message,
  open = true,
  duration = 4000,
  onClose,
  showClose = true,
  className,
  ...props
}) => {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [visible, setVisible] = React.useState(open);
  const [leaving, setLeaving] = React.useState(false);

  const style = VARIANT_STYLES[variant];

  // Auto-dismiss
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);

    if (open) {
      setVisible(true);
      setLeaving(false);
      timerRef.current = setTimeout(() => {
        setLeaving(true);
        timerRef.current = setTimeout(() => {
          setVisible(false);
          onClose?.();
        }, 300);
      }, duration);
    } else {
      setVisible(false);
    }

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [open, duration, onClose]);

  const handleDismiss = useCallback(() => {
    setLeaving(true);
    setTimeout(() => {
      setVisible(false);
      onClose?.();
    }, 300);
  }, [onClose]);

  if (!visible) return null;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        "fixed top-4 right-4 z-[200] max-w-sm w-full",
        "rounded-lg border shadow-lg",
        "backdrop-blur-sm",
        style.bg,
        style.border,
        visible && !leaving && "animate-[toastIn_0.3s_ease]",
        leaving && "animate-[toastOut_0.3s_ease_forwards]",
        className,
      )}
      style={{ zIndex: zIndex.toast, transition: transitions.slow }}
      {...props}
    >
      <div className="flex items-start gap-3 p-4">
        {/* Icon */}
        <span className={cn("mt-0.5 flex-shrink-0 rounded-full p-1.5", style.iconBg)}>
          <span className={style.textColor}>{ICONS[variant]}</span>
        </span>

        {/* Message */}
        <p className="flex-1 text-sm font-medium text-[var(--poe-text-primary,#ede6d6)] leading-relaxed">
          {message}
        </p>

        {/* Close */}
        {showClose && onClose && (
          <button
            onClick={handleDismiss}
            className="flex-shrink-0 mt-0.5 text-[var(--poe-text-dim,#7a7060)] hover:text-[var(--poe-text-primary)] transition-colors duration-150"
            aria-label="Dismiss"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
};
