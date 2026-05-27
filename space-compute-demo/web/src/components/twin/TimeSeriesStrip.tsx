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
  { key: 'solar_w',    label: 'Solar Input', unit: 'W',  digits: 0, color: '#F59E0B' },
  { key: 'payload_w',  label: 'Payload',     unit: 'W',  digits: 0, color: colors.accent },
  { key: 'battery_soc',label: 'Battery SOC', unit: '%',  digits: 0, color: '#22C55E',
    yMin: 0, yMax: 1, factor: 100 },
  { key: 'temp_c',     label: 'Temperature', unit: '°C', digits: 1, color: '#EF4444' },
  { key: 'gpu_util',   label: 'GPU Util',    unit: '%',  digits: 0, color: '#A78BFA',
    yMin: 0, yMax: 1, factor: 100 },
]

const HISTORY_S = 120

/**
 * TimeSeriesStrip — five stacked time-series charts (one per metric)
 * over the last 120 s.
 *
 * Each chart shows:
 *  - title + current value + unit, top
 *  - filled area + 1.5 px stroke + drop shadow
 *  - 3 horizontal gridlines (25/50/75 % of range)
 *  - y-axis tick labels: max (top-right) + min (bottom-right) per panel
 *  - dashed vertical "scars" wherever the SatelliteConfig changed
 *  - shared time axis labels at the bottom of the strip (-120s, -60s, now)
 */
export function TimeSeriesStrip() {
  const { current, series, scars } = useTwinTelemetry()

  return (
    <Card dense className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Live Telemetry · {HISTORY_S} s window
        </span>
        <span className="text-[10px] tabular text-text-lo">
          {scars.length > 0
            ? `${scars.length} configuration change${scars.length > 1 ? 's' : ''} in window`
            : 'no recent configuration changes'}
        </span>
      </div>

      <div className="mt-1 grid flex-1 min-h-0 grid-cols-5 gap-3">
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

      <div className="mt-1 grid grid-cols-5 gap-3 text-[9px] tabular text-text-faint">
        {SERIES.map((def) => (
          <div key={def.key} className="flex justify-between">
            <span>-{HISTORY_S}s</span>
            <span>-{Math.round(HISTORY_S / 2)}s</span>
            <span>now</span>
          </div>
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
    let lo = def.yMin !== undefined ? def.yMin * factor : Infinity
    let hi = def.yMax !== undefined ? def.yMax * factor : -Infinity
    if (def.yMin === undefined || def.yMax === undefined) {
      for (const v of data) {
        const u = v * factor
        if (def.yMin === undefined && u < lo) lo = u
        if (def.yMax === undefined && u > hi) hi = u
      }
      if (lo === Infinity)  lo = 0
      if (hi === -Infinity) hi = 1
      // Pad the range slightly so the line never sits on the top/bottom edge.
      const range = hi - lo
      if (range < 0.001) { lo -= 0.5; hi += 0.5 }
      else { lo -= range * 0.08; hi += range * 0.08 }
    }
    const w = 100
    const h = 100
    const pts: string[] = []
    for (let i = 0; i < n; i++) {
      const x = (i / (n - 1)) * w
      const y = h - ((data[i] * factor - lo) / (hi - lo)) * h
      pts.push(`${x.toFixed(2)},${y.toFixed(2)}`)
    }
    const pathStr = `M ${pts.join(' L ')}`
    const area = `${pathStr} L ${w.toFixed(2)},${h} L 0,${h} Z`
    return { path: pathStr, areaPath: area, yMin: lo, yMax: hi }
  }, [data, def])

  return (
    <div className="flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-md">
          {def.label}
        </span>
        <span className="flex items-baseline">
          <Num value={currentValue} digits={def.digits} animate={false} className="text-[14px] font-semibold text-text-hi" />
          <span className="ml-0.5 text-[10px] text-text-lo">{def.unit}</span>
        </span>
      </div>
      <div className="relative flex-1 min-h-0">
        {/* Right-edge y-axis tick labels. */}
        <div className="pointer-events-none absolute right-0 top-0 z-10 text-[9px] tabular text-text-faint">
          {fmt(yMax, def.digits, def.unit)}
        </div>
        <div className="pointer-events-none absolute right-0 bottom-0 z-10 text-[9px] tabular text-text-faint">
          {fmt(yMin, def.digits, def.unit)}
        </div>

        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
        >
          <defs>
            {/* Very subtle fill — just a hint under the line so the curve
                still feels weighted; primary visual is the stroke itself. */}
            <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%"   stopColor={def.color} stopOpacity={0.18} />
              <stop offset="100%" stopColor={def.color} stopOpacity={0} />
            </linearGradient>
          </defs>

          {/* Horizontal gridlines at 25 / 50 / 75 %. */}
          {[25, 50, 75].map((p) => (
            <line
              key={p} x1={0} x2={100} y1={p} y2={p}
              stroke="#A6B0C4"
              strokeWidth={0.4}
              vectorEffect="non-scaling-stroke"
              opacity={0.18}
              strokeDasharray="2 3"
            />
          ))}

          {/* Vertical time gridlines at 25 / 50 / 75 %. */}
          {[25, 50, 75].map((p) => (
            <line
              key={`v${p}`} x1={p} x2={p} y1={0} y2={100}
              stroke="#A6B0C4"
              strokeWidth={0.4}
              vectorEffect="non-scaling-stroke"
              opacity={0.10}
              strokeDasharray="2 3"
            />
          ))}

          {/* Subtle area fill, then the prominent line stroke. */}
          <path d={areaPath} fill={`url(#${gradId})`} />
          <path
            d={path}
            fill="none"
            stroke={def.color}
            strokeWidth={2.2}
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            style={{ filter: `drop-shadow(0 0 5px ${def.color})` }}
          />

          {/* Bright dot at the latest sample so the eye locks onto "now". */}
          {data.length >= 2 && (() => {
            const lastIdx = data.length - 1
            const factor = def.factor ?? 1
            const lo = yMin
            const hi = yMax
            const cx = 100
            const cy = 100 - ((data[lastIdx] * factor - lo) / (hi - lo)) * 100
            return (
              <circle
                cx={cx} cy={cy} r={2.4}
                fill={def.color}
                stroke="#0A0F1E"
                strokeWidth={1.2}
                vectorEffect="non-scaling-stroke"
                style={{ filter: `drop-shadow(0 0 5px ${def.color})` }}
              />
            )
          })()}

          {/* Config-change scars — vertical dashed white lines. */}
          {scars.map((s) => {
            const x = (s.index / Math.max(1, data.length - 1)) * 100
            return (
              <line
                key={`${s.sim_time_s}-${s.index}`}
                x1={x} x2={x} y1={0} y2={100}
                stroke="#E8EEFB"
                strokeWidth={1.0}
                strokeDasharray="3 3"
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

function fmt(v: number, digits: number, unit: string): string {
  // Compact formatter: 1.2k for thousands.
  const abs = Math.abs(v)
  if (abs >= 10000) return `${(v / 1000).toFixed(1)}k${unit ? ' ' + unit : ''}`
  return `${v.toFixed(digits)}${unit ? ' ' + unit : ''}`
}
