/**
 * Modal — overlay dialog with title, body, footer, and close button.
 *
 * @example
 * ```tsx
 * const [open, setOpen] = useState(false);
 * <Modal open={open} onClose={() => setOpen(false)} title="Confirm">
 *   <p>Are you sure?</p>
 *   <template #footer>
 *     <Button onClick={() => setOpen(false)}>Cancel</Button>
 *   </template>
 * </Modal>
 * ```
 */
"use client";

import * as React from "react";
import { useEffect, useRef, useCallback } from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { zIndex } from "./tokens";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Props ─────────────────────────────────────────────────────────────

export interface ModalProps extends Omit<React.DialogHTMLAttributes<HTMLDialogElement>, 'title'> {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  closable?: boolean;
  overlayClosable?: boolean;
  children?: React.ReactNode;
}

const SIZE_MAP: Record<string, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
};

// ── Component ─────────────────────────────────────────────────────────

/**
 * Modal — A dark-fantasy themed dialog/modal with overlay backdrop.
 */
export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  title,
  footer,
  size = "md",
  closable = true,
  overlayClosable = true,
  children,
  className,
  ...props
}) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  const handleClose = useCallback(() => {
    previousFocus.current?.focus();
    onClose();
  }, [onClose]);

  // Manage dialog open/close lifecycle
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open) {
      previousFocus.current = document.activeElement as HTMLElement;
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [open]);

  // Close on backdrop click
  const handleBackdropClick = (e: React.MouseEvent<HTMLDialogElement>) => {
    if (overlayClosable && e.target === e.currentTarget) {
      handleClose();
    }
  };

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onClick={handleBackdropClick}
      onClose={handleClose}
      className={cn(
        "backdrop:bg-[rgba(0,0,0,0.65)] backdrop:backdrop-blur-sm",
        "p-0 border-none rounded-xl",
        "bg-gradient-to-b from-[var(--poe-surface-2,#18151f)] to-[var(--poe-surface-1,#12101a)]",
        "border border-[rgba(74,60,90,0.55)]",
        "shadow-[inset_0_1px_0_rgba(255,255,255,0.03),0_18px_40px_rgba(0,0,0,0.45)]",
        "max-h-[85vh] overflow-y-auto",
        SIZE_MAP[size],
        className,
      )}
      style={{ zIndex: zIndex.modal }}
      {...props}
    >
      {/* Header */}
      {(title || closable) && (
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          {title && (
            <h2 className="font-rune text-lg font-bold tracking-wider text-[var(--poe-gold,#d4a94b)]">
              {title}
            </h2>
          )}
          {closable && (
            <button
              onClick={handleClose}
              className="ml-3 text-[var(--poe-text-dim)] hover:text-[var(--poe-text-primary)] transition-colors duration-150"
              aria-label="Close"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          )}
        </div>
      )}

      {/* Body */}
      <div className="px-6 pb-4 text-[var(--poe-text-body)]">{children}</div>

      {/* Footer */}
      {footer && (
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[rgba(74,60,90,0.35)]">
          {footer}
        </div>
      )}
    </dialog>
  );
};
