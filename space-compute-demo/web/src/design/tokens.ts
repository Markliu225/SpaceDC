/**
 * Design tokens — the single source of truth for colors / typography / motion.
 *
 * Tailwind config mirrors these (see ../../tailwind.config.js) and App.css
 * :root mirrors the subset the legacy pages use. When you change a value
 * here, mirror it there — and vice versa. They co-exist so SVG / Canvas /
 * Three.js code that can't consume Tailwind classes still reads the SAME
 * palette.
 *
 * Palette rules (one accent hue, chrome saturation < 80 %, no outer glows,
 * off-black graphite surfaces, shadows tinted to the bg hue):
 *   - `accent` is the ONLY brand hue. Status colors carry meaning, not brand.
 *   - Nothing in chrome glows. Selection is a ring (`border.focus`), not a halo.
 *   - Data-encoding colors (status / ribbons) are desaturated to sit with the
 *     neutrals; they are not accents.
 */

export const colors = {
  bg: {
    app:      '#0E1116',
    card:     '#151920',
    cardHi:   '#1B2029',
    inset:    '#10141A',
  },
  border: {
    weak:  'rgba(255,255,255,0.07)',
    med:   'rgba(255,255,255,0.12)',
    /** Selection ring. Also exposed under the historical `glow` key. */
    focus: 'rgba(92,155,214,0.55)',
    glow:  'rgba(92,155,214,0.55)',
  },
  text: {
    hi:    '#E6E9EF',
    md:    '#A3AAB8',
    lo:    '#6E7686',
    faint: '#5A6272',
  },
  accent:     '#5C9BD6',
  /** Accent-colored text on dark surfaces (AA-safe). */
  accentText: '#8FBCE8',
  /** Tinted fill for hover / selected surfaces. Historical name kept; not a glow. */
  accentGlow: 'rgba(92,155,214,0.14)',

  ok:   '#3FB871',
  okGlow:   'rgba(63,184,113,0.16)',
  info: '#7A8CD8',
  warn: '#E0A83A',
  err:  '#E0564F',

  // Donut segment palette.
  status: {
    online:  '#3FB871',
    eclipse: '#7A8CD8',
    standby: '#E0A83A',
    offline: '#E0564F',
  },

  // 6-hue ribbon palette for the orbit constellation (desaturated ~60 %).
  ribbons: [
    '#D57BC9', // magenta
    '#5CC3CF', // cyan
    '#E0B65A', // amber
    '#5DBE8E', // emerald
    '#9F8FD9', // violet
    '#E07A88', // rose
  ] as const,
} as const

export const typography = {
  sans: 'Geist, system-ui, sans-serif',
  mono: '"Geist Mono", "JetBrains Mono", ui-monospace, monospace',
} as const

export const motion = {
  // Match Tailwind keyframes durations so JS-driven transitions stay aligned.
  count:      400,
  card:       160,
  eventFade:  240,
  livePulse:  1600,
} as const

export type RibbonHue = (typeof colors.ribbons)[number]
