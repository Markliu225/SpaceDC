/** Tailwind config — applied ONLY to Overview-page surface area.
 *  Keep `content` scoped tightly so existing App.css pages aren't touched.
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
          app:    '#060912',
          card:   '#0E1424',
          'card-hi': '#131A2E',
          inset:  '#0A0F1E',
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
        accent: {
          DEFAULT: '#3B9EFF',
          glow:    '#3B9EFF44',
        },
        ok:   '#22C55E',
        info: '#3B82F6',
        warn: '#F59E0B',
        err:  '#EF4444',
        ribbon: {
          magenta: '#E879F9',
          cyan:    '#22D3EE',
          amber:   '#FBBF24',
          emerald: '#34D399',
          violet:  '#A78BFA',
          rose:    '#FB7185',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Geist Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        // Card recipe.
        card: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 8px 24px -12px rgba(0,0,0,0.6)',
        'card-hover': 'inset 0 1px 0 rgba(255,255,255,0.06), 0 12px 28px -10px rgba(0,0,0,0.7)',
        'card-glow': 'inset 0 1px 0 rgba(255,255,255,0.06), 0 0 0 1px rgba(59,158,255,0.35), 0 0 24px -4px rgba(59,158,255,0.25)',
      },
      backgroundImage: {
        card: 'linear-gradient(180deg,#101728 0%,#0C1322 100%)',
        'card-hi': 'linear-gradient(180deg,#15203A 0%,#101A30 100%)',
      },
      keyframes: {
        livePulse: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%':      { opacity: '0.3', transform: 'scale(1.15)' },
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
        floatY: {
          '0%, 100%': { transform: 'translateY(-3px)' },
          '50%':      { transform: 'translateY(3px)' },
        },
        ribbonBreath: {
          '0%, 100%': { opacity: '0.6' },
          '50%':      { opacity: '0.9' },
        },
        twinkle: {
          '0%, 100%': { opacity: '0.4' },
          '50%':      { opacity: '1' },
        },
      },
      animation: {
        'live-pulse':     'livePulse 1.6s ease-in-out infinite',
        'spark-draw':     'sparkDraw 900ms ease-out',
        'event-fade-in':  'eventFadeIn 240ms ease-out',
        'coverage-drift': 'coverageDrift 60s linear infinite',
        'float-y':        'floatY 4s ease-in-out infinite',
        'ribbon-breath':  'ribbonBreath 6s ease-in-out infinite',
        'twinkle':        'twinkle 2.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
