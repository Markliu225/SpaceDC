import { ComposableMap, Geographies, Geography } from 'react-simple-maps'
import { Card } from '../primitives'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { useId, useMemo } from 'react'

const TOPO = 'https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json'

const W = 800
const H = 320

export function CoverageMap() {
  const coverage = useTelemetryStore((s) => Math.round(s.network.coverage_pct))
  const gid = useId().replace(/:/g, '')
  const gradId = `cov-grad-${gid}`
  const swathPath = useMemo(() => buildSinusoidalSwath(W * 2, H), [])

  return (
    <Card className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Coverage Map
        </span>
        <span className="text-[11px] text-text-lo tabular">
          incl 50° · 24 sats
        </span>
      </div>

      <div className="relative flex-1 min-h-0 mt-1.5 overflow-hidden rounded-md bg-bg-inset">
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
      </div>

      {/* Progress bar footer */}
      <div className="mt-1.5">
        <div className="flex items-center justify-between text-[10px] tabular text-text-lo">
          <span>0%</span>
          <span className="text-text-md">{coverage}% global</span>
          <span>100%</span>
        </div>
        <div className="mt-0.5 h-1 w-full overflow-hidden rounded-full bg-bg-inset">
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

function buildSinusoidalSwath(width: number, height: number): string {
  const cy   = height / 2
  const amp  = height * 0.18
  const band = height * 0.10
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
