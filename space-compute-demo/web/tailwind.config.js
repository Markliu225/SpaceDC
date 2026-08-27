/** Tailwind config — applied ONLY to Overview-page surface area.
 *  Keep `content` scoped tightly so existing App.css pages aren't touched.
 *  Values mirror src/design/tokens.ts — keep them in sync.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/pages/OverviewPage.tsx',
    './src/pages/SatelliteTwinPage.tsx',
    './src/components/overview/**/*.{ts,tsx}',
    './src/components/primitives/**/*.{ts,tsx}',
    './src/components/twin/**/*.{ts,tsx}',
    './src/hooks/**/*.{ts,tsx}',
    './src/store/useTelemetryStore.ts',
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          app:    '#0E1116',
          card:   '#151920',
          'card-hi': '#1B2029',
          inset:  '#10141A',
        },
        border: {
          weak:  'rgba(255,255,255,0.07)',
          med:   'rgba(255,255,255,0.12)',
          focus: 'rgba(92,155,214,0.55)',
          // Historical alias for the selection ring — same value as `focus`.
          glow:  'rgba(92,155,214,0.55)',
        },
        text: {
          hi:    '#E6E9EF',
          md:    '#A3AAB8',
          lo:    '#6E7686',
          faint: '#5A6272',
        },
        accent: {
          DEFAULT: '#5C9BD6',
          text:    '#8FBCE8',
          soft:    'rgba(92,155,214,0.14)',
          // Historical alias — now a tinted fill, never a glow.
          glow:    'rgba(92,155,214,0.14)',
        },
        ok:   '#3FB871',
        info: '#7A8CD8',
        warn: '#E0A83A',
        err:  '#E0564F',
        ribbon: {
          magenta: '#D57BC9',
          cyan:    '#5CC3CF',
          amber:   '#E0B65A',
          emerald: '#5DBE8E',
          violet:  '#9F8FD9',
          rose:    '#E07A88',
        },
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', 'sans-serif'],
        mono: ['"Geist Mono"', '"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        // Card recipe: shadows tinted to the bg hue, light from above, no halo.
        card: '0 1px 0 rgba(6,9,14,0.35), 0 6px 16px -10px rgba(6,9,14,0.7)',
        'card-hover': '0 1px 0 rgba(6,9,14,0.35), 0 10px 20px -12px rgba(6,9,14,0.8)',
        'card-focus': '0 0 0 1px rgba(92,155,214,0.55)',
        // Historical alias for the selected ring — same as `card-focus`.
        'card-glow': '0 0 0 1px rgba(92,155,214,0.55)',
        // Modal / overlay dialogs: deeper drop, still bg-tinted, no halo.
        modal: '0 24px 48px -16px rgba(6,9,14,0.8)',
      },
      backgroundImage: {
        // Flat fills. Kept as backgroundImage keys so the existing `bg-card` /
        // `bg-card-hi` call sites keep compiling without a gradient.
        card: 'linear-gradient(#151920,#151920)',
        'card-hi': 'linear-gradient(#1B2029,#1B2029)',
      },
      keyframes: {
        livePulse: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.35' },
        },
        sparkDraw: {
          '0%':   { strokeDashoffset: '300' },
          '100%': { strokeDashoffset: '0' },
        },
        eventFadeIn: {
          '0%':   { opacity: '0', transform: 'translateY(-6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        coverageDrift: {
          '0%':   { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
      },
      animation: {
        'live-pulse':     'livePulse 1.6s ease-in-out infinite',
        'spark-draw':     'sparkDraw 900ms ease-out',
        'event-fade-in':  'eventFadeIn 240ms ease-out',
        'coverage-drift': 'coverageDrift 60s linear infinite',
      },
    },
  },
  plugins: [],
}
