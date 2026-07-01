/**
 * Design Tokens
 *
 * Centralized design token system derived from globals.css CSS variables.
 * All values reference the PoE2 dark-fantasy theme palette.
 */

// ── Colors ───────────────────────────────────────────────────────────

export const colors = {
  // Backgrounds
  bg: {
    DEFAULT: '#0f0916',      // --poe-void-deep
    elevated: '#12101a',     // --poe-surface-1
    panel: '#14161a',        // --ninja-panel
    panelHover: '#1a1c22',   // --ninja-panel-hover
    surface2: '#18151f',     // --poe-surface-2
    surface3: '#1e1a26',     // --poe-surface-3
    elevatedSurface: '#23202b', // --poe-surface-elevated
  },

  // Borders
  border: {
    DEFAULT: '#2c2434',      // --poe-border
    strong: '#3e3248',       // --poe-border-strong
    accentSoft: 'rgba(201,169,110,0.28)',
  },

  // Accents
  accent: {
    gold: '#d4a94b',         // --poe-gold
    goldBright: '#f3cc6e',   // --poe-gold-bright
    rune: '#c9a96e',         // --poe-rune
    dim: '#b08d3a',          // --ninja-accent-dim
    glow: 'rgba(224,185,94,0.32)',
  },

  // Text
  text: {
    primary: '#ede6d6',      // --poe-text-primary
    secondary: '#bfb59f',    // --poe-text-secondary
    dim: '#7a7060',          // --poe-text-dim
    body: '#d4c8b8',         // --poe-text-body
    muted: '#c7bfae',        // --ninja-text-muted
    dimmed: '#968c7a',       // --ninja-text-dim
  },

  // Semantic
  semantic: {
    danger: '#ef4444',       // --ninja-danger
    warning: '#f59e0b',      // --ninja-warning
    corruption: '#7a1f1f',   // --poe-corruption
    verdigris: '#3d5a54',    // --poe-verdigris
  },

  // Glows (alpha channels)
  glow: {
    void: 'rgba(74,45,117,0.35)',
    corruption: 'rgba(154,38,38,0.35)',
    gold: 'rgba(212,169,75,0.45)',
    runeDim: 'rgba(201,169,110,0.25)',
  },
} as const;

// ── Spacing ──────────────────────────────────────────────────────────

export const spacing = {
  xs: '0.25rem',   // 4px
  sm: '0.5rem',    // 8px
  md: '0.75rem',   // 12px
  lg: '1rem',      // 16px
  xl: '1.25rem',   // 20px
  '2xl': '1.5rem', // 24px
  '3xl': '2rem',   // 32px
  '4xl': '2.5rem', // 40px
} as const;

// ── Font Sizes ───────────────────────────────────────────────────────

export const fontSizes = {
  xs: '0.7rem',
  sm: '0.78rem',
  base: '0.875rem',  // 14px
  md: '0.9rem',
  lg: '1rem',
  xl: '1.1rem',
  '2xl': '1.6rem',
  hero: 'clamp(1.8rem, 4.2vw, 2.6rem)',
} as const;

// ── Font Weights ─────────────────────────────────────────────────────

export const fontWeights = {
  normal: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
  extrabold: '800',
  black: '900',
} as const;

// ── Border Radius ────────────────────────────────────────────────────

export const borderRadius = {
  none: '0',
  sm: '0.25rem',
  md: '0.5rem',
  lg: '0.65rem',
  xl: '0.95rem',
  '2xl': '1rem',
  full: '9999px',
} as const;

// ── Shadows ──────────────────────────────────────────────────────────

export const shadows = {
  none: 'none',
  sm: '0 1px 2px rgba(0,0,0,0.3)',
  md: '0 4px 12px rgba(0,0,0,0.35)',
  lg: '0 18px 40px rgba(0,0,0,0.45)',
  // Gold glow
  gold: '0 0 26px rgba(200,164,97,0.35)',
  goldStrong: '0 0 34px rgba(200,164,97,0.5)',
  // Corruption glow
  void: '0 0 22px rgba(120,75,165,0.18)',
  // Panel inner highlight
  inset: 'inset 0 1px 0 rgba(255,255,255,0.04)',
  accent: `
    0 0 28px rgba(212,169,75,0.18),
    0 0 80px rgba(120,80,170,0.08),
    ${'inset 0 1px 0 rgba(255,255,255,0.05)'},
    0 18px 40px rgba(0,0,0,0.55)
  `,
} as const;

// ── Transitions ──────────────────────────────────────────────────────

export const transitions = {
  fast: '0.15s ease',
  DEFAULT: '0.2s ease',
  slow: '0.25s ease',
} as const;

// ── Z-Index Scale ────────────────────────────────────────────────────

export const zIndex = {
  dropzone: 10,
  nav: 50,
  modal: 100,
  toast: 200,
} as const;

// ── Icon Size Presets ────────────────────────────────────────────────

export const iconSizes = {
  sm: '1rem',
  md: '1.25rem',
  lg: '1.5rem',
  xl: '1.75rem',
} as const;
