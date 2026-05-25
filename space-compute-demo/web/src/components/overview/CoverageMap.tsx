import { ComposableMap, Geographies, Geography } from 'react-simple-maps'
import { Card } from '../primitives'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { useId, useMemo } from 'react'

/**
 * CoverageMap — flat world map with a drifting cyan orbital swath.
 *
 * - Continents fill #1B233A, no borders.
 * - Swath is a sinusoidal SVG path (amplitude ~30°, period 360°, inclination 50°),
 *   filled with a horizontal cyan gradient. Tiled 2x so we can translate by -50%
 *   over 60s for a seamless drift loop.
 * - Footer: 4px progress bar with coverage_pct.
 */
const TOPO = 'https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json'

const W = 800
const H = 320

export function CoverageMap() {
  const coverage = useTelemetryStore((s) => Math.round(s.network.coverage_pct))
  const gid = useId().replace(/:/g, '')
  const gradId = `cov-grad-${gid}`

  // Pre-compute the swath path tiled twice across [0, 2*W].
  const swathPath = useMemo(() => buildSinusoidalSwath(W * 2, H), [])

  return (
    <Card>
      <div className="mb-3 flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Coverage Map
        </span>
        <span className="text-[12px] text-text-lo tabular">
          inclination 50° · 24 sats
        </span>
      </div>

      <div className="relative h-[300px] overflow-hidden rounded-md bg-bg-inset">
        <ComposableMap
          projection="geoEqualEarth"
          projectionConfig={{ scale: 145 }}
          width={W}
          height={H}
          style={{ width: '100%', height: '100%' }}
        >
          <Geographies geography={TOPO}>
            {({ geographies }) =>
              geographies.map((geo) => (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill="#1B233A"
                  stroke="transparent"
                  style={{
                    default: { outline: 'none' },
                    hover:   { outline: 'none', fill: '#23304E' },
                    pressed: { outline: 'none' },
                  }}
                />
              ))
            }
          </Geographies>

          {/* Coverage swath — absolute SVG group; translated by CSS animation. */}
          <defs>
            <linearGradient id={gradId} x1="0%" x2="100%" y1="0%" y2="0%">
              <stop offset="0%"   stopColor="#3B9EFF" stopOpacity="0.15" />
              <stop offset="50%"  stopColor="#3B9EFF" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#3B9EFF" stopOpacity="0.15" />
            </linearGradient>
          </defs>
          <g className="animate-coverage-drift" style={{ transformOrigin: '0 0' }}>
            <path d={swathPath} fill={`url(#${gradId})`} />
          </g>
        </ComposableMap>

        {/* Top-left badge */}
        <div className="absolute left-3 top-3 rounded bg-bg-inset/70 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-text-lo backdrop-blur">
          Orbital Swath · 50° incl.
        </div>
      </div>

      {/* Progress bar footer */}
      <div className="mt-3">
        <div className="flex items-center justify-between text-[10px] tabular text-text-lo">
          <span>0%</span>
          <span className="text-text-md">Coverage</span>
          <span>100%</span>
        </div>
        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-bg-inset">
          <div
            className="h-full rounded-full transition-[width] duration-500 ease-out"
            style={{
              width: `${coverage}%`,
              background: 'linear-gradient(90deg, #3B9EFF 0%, #E8EEFB 100%)',
              boxShadow: '0 0 8px rgba(59,158,255,0.4)',
            }}
          />
        </div>
      </div>
    </Card>
  )
}

/**
 * Build a closed sinusoidal swath path covering [0..W] × [0..H].
 * The waveform has period = W / 2 (so the path repeats twice across the
 * tiled width), amplitude = 0.18*H, centered at H/2.
 */
function buildSinusoidalSwath(width: number, height: number): string {
  const cy   = height / 2
  const amp  = height * 0.18
  const band = height * 0.10  // half-thickness of the swath band
  const period = width / 2
  const steps = 200

  const top: string[] = []
  const bot: string[] = []
  for (let i = 0; i <= steps; i++) {
    const x = (i / steps) * width
    const y = cy + amp * Math.sin((x / period) * Math.PI * 2)
    top.push(`${x.toFixed(1)},${(y - band).toFixed(1)}`)
    bot.push(`${x.toFixed(1)},${(y + band).toFixed(1)}`)
  }
  return `M ${top.join(' L ')} L ${bot.reverse().join(' L ')} Z`
}
