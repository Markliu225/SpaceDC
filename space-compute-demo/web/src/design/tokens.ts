/**
 * Design tokens — the single source of truth for colors / typography / motion.
 *
 * Tailwind config mirrors these (see ../../tailwind.config.js). When you
 * change a value here, mirror it there — and vice versa. They co-exist so
 * SVG / Canvas / Three.js code that can't consume Tailwind classes still
 * reads the SAME palette.
 */

export const colors = {
  bg: {
    app:      '#060912',
    card:     '#0E1424',
    cardHi:   '#131A2E',
    inset:    '#0A0F1E',
  },
  border: {
    weak: 'rgba(255,255,255,0.06)',
    med:  'rgba(255,255,255,0.10)',
    glow: 'rgba(59,158,255,0.35)',
  },
  text: {
    hi:    '#E8EEFB',
    md:    '#A6B0C4',
    lo:    '#6B7691',
    faint: '#4A5470',
  },
  accent:     '#3B9EFF',
  accentGlow: '#3B9EFF44',

  ok:   '#22C55E',
  okGlow:   '#22C55E33',
  info: '#3B82F6',
  warn: '#F59E0B',
  err:  '#EF4444',

  // Donut segment palette.
  status: {
    online:  '#22C55E',
    eclipse: '#3B82F6',
    standby: '#F59E0B',
    offline: '#EF4444',
  },

  // 6-hue ribbon palette for the orbit constellation.
  ribbons: [
    '#E879F9', // magenta
    '#22D3EE', // cyan
    '#FBBF24', // amber
    '#34D399', // emerald
    '#A78BFA', // violet
    '#FB7185', // rose
  ] as const,
} as const

export const typography = {
  sans: 'Inter, system-ui, sans-serif',
  mono: '"JetBrains Mono", "Geist Mono", ui-monospace, monospace',
} as const

export const motion = {
  // Match Tailwind keyframes durations so JS-driven transitions stay aligned.
  count:      400,
  card:       160,
  eventFade:  240,
  livePulse:  1600,
  ribbonBreath: 6000,
} as const

export type RibbonHue = (typeof colors.ribbons)[number]
