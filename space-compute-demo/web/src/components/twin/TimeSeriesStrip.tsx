import { useId, useMemo } from 'react'
import { Card, Num } from '../primitives'
import { colors } from '../../design/tokens'
import { useTwinTelemetry, type TwinScar } from '../../hooks/useTwinTelemetry'
import { COMPARE_PALETTE } from './comparePalette'

/** One what-if overlay line for a Mini — right-aligned growing ring. */
interface OverlayLine {
  color: string
  data: number[]
}

/** Nested stroke widths by variant index (draw order = pick order): the
 *  first variant is widest and drawn first, so coincident curves render as
 *  nested colored edges instead of one color hiding the others. */
const OVERLAY_WIDTHS = [3.8, 2.7, 1.8, 1.1]

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
 *  - its own framed panel + time axis (-120s, -60s, now)
 */
export function TimeSeriesStrip() {
  const { current, series, scars, compare } = useTwinTelemetry()

  return (
    <Card dense className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Live Telemetry · {HISTORY_S} s window
        </span>
        {compare ? (
          // Live what-if legend — variant labels wear their curve colors'
          // swatches; text stays in ink tokens.
          <span className="flex items-center gap-3" data-testid="compare-legend">
            <span className="text-[10px] uppercase tracking-[0.08em] text-accent">
              What-if · {compare.dimension_label}
            </span>
            {compare.variants.map((v, i) => (
              <span key={String(v.value)} className="flex items-center gap-1 text-[10px] text-text-md">
                <span
                  className="inline-block h-[3px] w-4 rounded-full"
                  style={{ background: COMPARE_PALETTE[i] }}
                />
                {v.label}
              </span>
            ))}
          </span>
        ) : (
          <span className="text-[10px] tabular text-text-lo">
            {scars.length > 0
              ? `${scars.length} configuration change${scars.length > 1 ? 's' : ''} in window`
              : 'no recent configuration changes'}
          </span>
        )}
      </div>

      <div className="mt-1.5 grid flex-1 min-h-0 grid-cols-5 gap-2.5">
        {SERIES.map((def) => (
          <Mini
            key={def.key}
            def={def}
            data={series[def.key]}
            currentValue={(current[def.key as keyof typeof current] as number) * (def.factor ?? 1)}
            scars={scars}
            overlays={compare?.variants.map((v, i) => ({
              color: COMPARE_PALETTE[i],
              data: v.series[def.key],
            }))}
            // While a comparison runs the live trace yields the stage: one
            // variant is usually the current value anyway, so keeping the
            // solid line would just double-draw it and clutter the read.
            liveHidden={compare !== null}
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
  /** Live what-if variant curves — right-aligned growing rings. */
  overlays?: OverlayLine[]
  /** Hide the live trace (comparison running — variants own the panel). */
  liveHidden?: boolean
}

function Mini({ def, data, currentValue, scars, overlays, liveHidden }: MiniProps) {
  const gid     = useId().replace(/:/g, '')
  const gradId  = `tw-grad-${gid}`

  const { path, areaPath, yMin, yMax, overlayPaths } = useMemo(() => {
    const n = data.length
    if (n < 2) return { path: '', areaPath: '', yMin: 0, yMax: 1, overlayPaths: [] as { color: string; d: string }[] }
    const factor = def.factor ?? 1
    let lo = def.yMin !== undefined ? def.yMin * factor : Infinity
    let hi = def.yMax !== undefined ? def.yMax * factor : -Infinity
    // With the live trace hidden (comparison running), the variants alone
    // drive the autoscale — a hidden line must not stretch the range. Until
    // the rings have ≥ 2 samples, fall back to the live data so the scale
    // doesn't collapse in the first second.
    const overlaysReady = (overlays ?? []).some((ov) => ov.data.length >= 2)
    const scaleFromLive = !liveHidden || !overlaysReady
    if (def.yMin === undefined || def.yMax === undefined) {
      // Autoscale over the visible traces, so a diverging variant never
      // clips off the top/bottom of the panel.
      if (scaleFromLive) {
        for (const v of data) {
          const u = v * factor
          if (def.yMin === undefined && u < lo) lo = u
          if (def.yMax === undefined && u > hi) hi = u
        }
      }
      for (const ov of overlays ?? []) {
        for (const v of ov.data) {
          const u = v * factor
          if (def.yMin === undefined && u < lo) lo = u
          if (def.yMax === undefined && u > hi) hi = u
        }
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

    // Overlay polylines share the y-scale and are RIGHT-aligned: a ring of
    // V samples occupies the window's last V slots (it started mid-window).
    const overlayPaths: { color: string; d: string }[] = []
    for (const ov of overlays ?? []) {
      const ring = ov.data.length > n ? ov.data.slice(ov.data.length - n) : ov.data
      const V = ring.length
      if (V < 2) continue
      const parts: string[] = []
      for (let i = 0; i < V; i++) {
        const x = ((n - V + i) / (n - 1)) * w
        const y = h - ((ring[i] * factor - lo) / (hi - lo)) * h
        parts.push(`${x.toFixed(2)},${y.toFixed(2)}`)
      }
      overlayPaths.push({ color: ov.color, d: `M ${parts.join(' L ')}` })
    }
    return { path: pathStr, areaPath: area, yMin: lo, yMax: hi, overlayPaths }
  }, [data, def, overlays, liveHidden])

  const factor = def.factor ?? 1
  return (
    // Each metric lives in its OWN framed panel — border + inset background
    // + its own time axis — so the five charts read as five instruments, not
    // one blurred strip.
    <div className="flex min-h-0 flex-col rounded-md border border-border-weak bg-bg-inset/40 px-2 pb-1 pt-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-md">
          {def.label}
        </span>
        {liveHidden && overlays && overlays.length > 0 ? (
          // Comparison running: the live number matches no visible curve, so
          // show each VARIANT's current value instead (dot carries the hue,
          // the number stays in ink) — read a curve straight off its color.
          <span className="flex items-baseline gap-1.5">
            {overlays.map((ov, i) => (
              <span key={i} className="flex items-center gap-0.5">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: ov.color }}
                />
                <span className="text-[11px] font-semibold tabular text-text-hi">
                  {ov.data.length > 0
                    ? fmt(ov.data[ov.data.length - 1] * factor, def.digits, '')
                    : '—'}
                </span>
              </span>
            ))}
            <span className="ml-0.5 text-[10px] text-text-lo">{def.unit}</span>
          </span>
        ) : (
          <span className="flex items-baseline">
            <Num value={currentValue} digits={def.digits} animate={false} className="text-[14px] font-semibold text-text-hi" />
            <span className="ml-0.5 text-[10px] text-text-lo">{def.unit}</span>
          </span>
        )}
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

          {/* Subtle area fill, then the prominent line stroke — hidden while
              a comparison runs (the variants own the panel; one of them is
              usually the current value anyway). */}
          {!liveHidden && (
            <>
              <path d={areaPath} fill={`url(#${gradId})`} />
              <path
                d={path}
                fill="none"
                stroke={def.color}
                strokeWidth={2.2}
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
                style={{ filter: `drop-shadow(0 0 2px ${def.color})` }}
              />
            </>
          )}

          {/* Live what-if overlays — solid matte strokes, NO glow. NESTED
              widths (wide → narrow in draw order): when curves coincide —
              which they legitimately do whenever the compared knob doesn't
              move a metric — every variant still shows as a visible edge
              around the narrower ones on top, instead of the last-drawn
              color swallowing the rest. */}
          {overlayPaths.map((op, i) => (
            <path
              key={i}
              data-testid="compare-overlay"
              d={op.d}
              fill="none"
              stroke={op.color}
              strokeWidth={OVERLAY_WIDTHS[i] ?? 1.2}
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {/* Bright dot at the latest sample so the eye locks onto "now". */}
          {!liveHidden && data.length >= 2 && (() => {
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
                style={{ filter: `drop-shadow(0 0 2px ${def.color})` }}
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

      {/* Per-panel time axis. */}
      <div className="mt-0.5 flex justify-between text-[9px] tabular text-text-faint">
        <span>-{HISTORY_S}s</span>
        <span>-{Math.round(HISTORY_S / 2)}s</span>
        <span>now</span>
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
