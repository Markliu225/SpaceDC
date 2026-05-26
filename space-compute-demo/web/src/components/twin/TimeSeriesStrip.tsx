import { useId, useMemo } from 'react'
import { Card, Num } from '../primitives'
import { colors } from '../../design/tokens'
import { useTwinTelemetry, type TwinScar } from '../../hooks/useTwinTelemetry'

interface SeriesDef {
  key: keyof ReturnType<typeof useTwinTelemetry>['series']
  label: string
  unit: string
  digits: number
  color: string
  /** Optional fixed y-axis range — when omitted, autoscales from data. */
  yMin?: number
  yMax?: number
  /** Format multiplier (e.g. 100 for SOC ⇒ %). */
  factor?: number
}

const SERIES: SeriesDef[] = [
  { key: 'solar_w',    label: 'Solar In',    unit: 'W',      digits: 0, color: '#F59E0B' },
  { key: 'payload_w',  label: 'Payload',     unit: 'W',      digits: 0, color: colors.accent },
  { key: 'battery_soc',label: 'Battery SOC', unit: '%',      digits: 0, color: '#22C55E', yMin: 0, yMax: 1, factor: 100 },
  { key: 'temp_c',     label: 'Temp',        unit: '°C',     digits: 1, color: '#EF4444' },
  { key: 'gpu_util',   label: 'GPU Util',    unit: '%',      digits: 0, color: '#A78BFA', yMin: 0, yMax: 1, factor: 100 },
]

/**
 * TimeSeriesStrip — 5 sparklines side-by-side, 120s rolling window.
 * Each sparkline annotates SatelliteConfig changes with a 1px dashed
 * vertical "scar" at the index where the change happened; the scar
 * persists until it scrolls off the left edge.
 *
 * Values come from useTwinTelemetry() — fully client-side in Phase 1;
 * Phase 2 will replace the underlying derivation with state_update echo.
 */
export function TimeSeriesStrip() {
  const { current, series, scars } = useTwinTelemetry()

  return (
    <Card dense className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Live Telemetry · 120 s
        </span>
        <span className="text-[10px] tabular text-text-lo">
          {scars.length > 0
            ? `${scars.length} config change${scars.length > 1 ? 's' : ''} in window`
            : 'no recent config changes'}
        </span>
      </div>

      <div className="mt-2 grid flex-1 min-h-0 grid-cols-5 gap-3">
        {SERIES.map((def) => (
          <Mini
            key={def.key}
            def={def}
            data={series[def.key]}
            currentValue={(current[def.key as keyof typeof current] as number) * (def.factor ?? 1)}
            scars={scars}
          />
        ))}
      </div>
    </Card>
  )
}

interface MiniProps {
  def: SeriesDef
  data: number[]
  currentValue: number
  scars: TwinScar[]
}

function Mini({ def, data, currentValue, scars }: MiniProps) {
  const gid     = useId().replace(/:/g, '')
  const gradId  = `tw-grad-${gid}`

  const { path, areaPath, yMin, yMax } = useMemo(() => {
    const n = data.length
    if (n < 2) return { path: '', areaPath: '', yMin: 0, yMax: 1 }
    const factor = def.factor ?? 1
    let lo = def.yMin ?? Infinity
    let hi = def.yMax ?? -Infinity
    if (def.yMin === undefined || def.yMax === undefined) {
      for (const v of data) {
        const u = v * factor
        if (def.yMin === undefined && u < lo) lo = u
        if (def.yMax === undefined && u > hi) hi = u
      }
      if (lo === Infinity)  lo = 0
      if (hi === -Infinity) hi = 1
      if (hi - lo < 0.001) { lo -= 0.5; hi += 0.5 }
    } else {
      lo = def.yMin * factor
      hi = def.yMax * factor
    }
    const w = 100  // viewBox width
    const h = 100  // viewBox height
    const points: string[] = []
    for (let i = 0; i < n; i++) {
      const x = (i / (n - 1)) * w
      const y = h - ((data[i] * factor - lo) / (hi - lo)) * h
      points.push(`${x.toFixed(2)},${y.toFixed(2)}`)
    }
    const pathStr = `M ${points.join(' L ')}`
    const area = `${pathStr} L ${w.toFixed(2)},${h} L 0,${h} Z`
    return { path: pathStr, areaPath: area, yMin: lo, yMax: hi }
  }, [data, def])

  void yMin; void yMax  // reserved for tooltip / scale display later

  return (
    <div className="flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-md">
          {def.label}
        </span>
        <span className="flex items-baseline">
          <Num value={currentValue} digits={def.digits} animate={false} className="text-[13px] font-semibold text-text-hi" />
          <span className="ml-0.5 text-[10px] text-text-lo">{def.unit}</span>
        </span>
      </div>
      <div className="relative flex-1 min-h-0">
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
        >
          <defs>
            <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%"   stopColor={def.color} stopOpacity={0.45} />
              <stop offset="100%" stopColor={def.color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#${gradId})`} />
          <path
            d={path}
            fill="none"
            stroke={def.color}
            strokeWidth={1.2}
            vectorEffect="non-scaling-stroke"
            style={{ filter: `drop-shadow(0 0 3px ${def.color}88)` }}
          />
          {scars.map((s) => {
            // index maps 0..n-1 onto x 0..100; n = data.length.
            const x = (s.index / Math.max(1, data.length - 1)) * 100
            return (
              <line
                key={`${s.sim_time_s}-${s.index}`}
                x1={x} x2={x} y1={0} y2={100}
                stroke="#E8EEFB"
                strokeWidth={0.8}
                strokeDasharray="2 2"
                vectorEffect="non-scaling-stroke"
                opacity={0.55}
              />
            )
          })}
        </svg>
      </div>
    </div>
  )
}
