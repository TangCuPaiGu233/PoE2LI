/**
 * UI Component Library — Barrel Export
 *
 * Unified public API for all shared UI components.
 * Import from '@components/ui' or relative path.
 *
 * @example
 * ```tsx
 * import { Button, Card, Input, Modal, Toast, Spinner, Badge, Select } from '@/components/ui';
 * ```
 */

// ── Design Tokens ─────────────────────────────────────────────────────

export {
  colors,
  spacing,
  fontSizes,
  fontWeights,
  borderRadius,
  shadows,
  transitions,
  zIndex,
  iconSizes,
} from "./tokens";
export type { ButtonVariant, ButtonSize } from "./Button";
export type { CardVariant } from "./Card";
export type { ToastVariant } from "./Toast";
export type { SpinnerSize, SpinnerColor } from "./Spinner";
export type { BadgeVariant, BadgeSize } from "./Badge";

// ── Components ────────────────────────────────────────────────────────

export { Button } from "./Button";
export type { ButtonProps } from "./Button";

export { Card } from "./Card";
export type { CardProps } from "./Card";

export { Input } from "./Input";
export type { InputProps } from "./Input";

export { Select } from "./Select";
export type { SelectProps } from "./Select";

export { Modal } from "./Modal";
export type { ModalProps } from "./Modal";

export { Toast } from "./Toast";
export type { ToastProps } from "./Toast";

export { Spinner } from "./Spinner";
export type { SpinnerProps } from "./Spinner";

export { Badge } from "./Badge";
export type { BadgeProps } from "./Badge";
