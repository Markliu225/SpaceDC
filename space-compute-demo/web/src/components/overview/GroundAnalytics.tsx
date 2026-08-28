import { useEffect, useMemo, useRef, useState } from 'react'
import type { JSX } from 'react'
import { Loader2, MapPin, Radio, Sun } from 'lucide-react'
import type { CommsBand, GroundTargetState } from '../../types/messages'
import {
  GROUND_CONFIG_DEFAULTS,
  type CoverageSample, type EnergySample, type GroundConfig, type useOrbitDesign,
} from '../../hooks/useOrbitDesign'
import { colors } from '../../design/tokens'
import { useTelemetryStore } from '../../store/useTelemetryStore'

/**
 * Ground-station analytics for the Overview panel.
 *
 * Charts driven by the live StatePacket:
 *   - CoverageCharts     — visible-sat count + aggregate bandwidth over time
 *                          (StatePacket.ground_target)
 *   - SolarHistogram     — solar collection per collection-factor bin
 *                          (StatePacket.ground_target)
 *   - EnergyHarvestChart — whole-constellation solar harvest over the rolling
 *                          window (StatePacket.constellation — no ground
 *                          target needed, eclipse included, so it renders
 *                          standalone at full height when nothing is marked)
 *
 * The controls that drive those charts live here too, so the Coverage / Solar
 * tabs own their own inputs:
 *   - GroundStationControls — mark toggle · elevation mask · comms band, plus
 *                             the live readout and the pass analysis
 *   - SolarBinControl       — the histogram's per 5 / per 10 bin width
 *
 * Sizing contract with the panel — it owns the flex split, this file owns what
 * happens inside each slot:
 *   - Every block is `flex-1 min-h-0` and imposes NO minimum height, so the
 *     panel's percentages are the only thing deciding the split.
 *   - Under DENSE_H px a chart sheds secondary chrome (footer axis row, extra
 *     gridlines, long titles) instead of squeezing the plot to nothing. The
 *     switch is measured per block with a ResizeObserver, so it follows
 *     whatever height the panel actually hands out.
 *   - `GroundStationControls compact` is a genuinely smaller layout (three
 *     dense rows, no section header — roughly half the height), NOT a
 *     feature-stripped one: toggle, live readout, mask, bands, analyze button
 *     and pass strip are all still present.
 *
 * Each block keeps its `data-testid` on the WRAPPER in both the populated and
 * the empty branch, with `data-state="live" | "empty"` telling them apart, so
 * an e2e can assert presence and state independently.
 */

// Series hues come from the token palette: solar = the desaturated amber
// ribbon (data hue, not the warn status), visible-sat count = the app accent.
const SOLAR_HUE = colors.ribbons[2]
const VISIBLE_HUE = colors.accent

/**
 * Real seconds represented by one telemetry sample. State is broadcast once per
 * sim second and the sim runs at `time_scale`, so one sample covers
 * `time_scale` real seconds of collection. The live value is served on the
 * constellation detail and is what `hooks/gmstClock.ts` spins the Earth by —
 * read it rather than assuming, so raising the backend's TIME_SCALE cannot
 * silently leave the kWh figure scaled by the old rate. The constant is only
 * the pre-first-fetch fallback and matches the backend's current default.
 */
const FALLBACK_SAMPLE_REAL_S = 60

/**
 * Box height (px) below which a chart switches to dense chrome. Sized so the
 * ~60 px slot the rebalanced Coverage/Solar tabs give a line chart is dense,
 * while a chart that owns its tab is not.
 */
const DENSE_H = 78
/** Re-expand only 8 px above the threshold so a box parked on the boundary
 *  cannot oscillate between the two layouts. */
const DENSE_HYSTERESIS = 8

/**
 * Measure a block's own height and report whether it is too short for full
 * chrome. The block is `overflow-hidden` and sized by the parent's flex split,
 * so changing the layout cannot feed back into the measurement.
 */
function useDenseBox<T extends HTMLElement>(threshold = DENSE_H) {
  const ref = useRef<T | null>(null)
  const [dense, setDense] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const h = entries[entries.length - 1]?.contentRect.height ?? 0
      if (h <= 0) return   // hidden tab — keep the last decision
      setDense((prev) => (prev ? h < threshold + DENSE_HYSTERESIS : h < threshold))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [threshold])
  return [ref, dense] as const
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded border
                    border-dashed border-border-weak px-3 text-center text-[11px] text-text-faint">
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Coverage — two stacked line charts (no dual-axis): visible sats + Mbps.
// The wrapper carries the testid in both branches; `data-state` separates them.
// ---------------------------------------------------------------------------
export function CoverageCharts({ history, gt }: {
  history: CoverageSample[]; gt: GroundTargetState | null
}) {
  const live = gt?.enabled === true
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5"
         data-testid="coverage-charts" data-state={live ? 'live' : 'empty'}>
      {!live || !gt ? (
        <EmptyHint>Mark the ground station to chart visibility over time.</EmptyHint>
      ) : (
        <>
          <LineChart
            title="Visible satellites"
            short="Visible"
            data={history.map((s) => s.visible)}
            current={gt.visible_sats}
            unit=""
            color={VISIBLE_HUE}
            digits={0}
          />
          <LineChart
            title={`Aggregate bandwidth · ${gt.band_label}`}
            short={gt.band_label}
            data={history.map((s) => s.mbps)}
            current={gt.aggregate_mbps}
            unit="Mbps"
            color={SOLAR_HUE}
            digits={0}
          />
        </>
      )}
    </div>
  )
}

function LineChart({ title, short, data, current, unit, color, digits, sub, foot, axisDigits = 0, zeroBased = false }: {
  title: string; data: number[]; current: number
  unit: string; color: string; digits: number
  /** Shorter title, used when the box is too short for the full one. */
  short?: string
  /** Secondary figure after the current value (e.g. a cumulative total). */
  sub?: string
  /** Centred note on the time axis; folds up into the header when dense. */
  foot?: string
  /** Decimals on the min/max axis labels. */
  axisDigits?: number
  /** Scale from 0 instead of the data's own min — for magnitude series where
   *  "how close to full" is the question and a constant must read as flat. */
  zeroBased?: boolean
}) {
  const [boxRef, dense] = useDenseBox<HTMLDivElement>()
  const { path, lo, hi } = useMemo(() => {
    const n = data.length
    if (n < 2) return { path: '', lo: 0, hi: 1 }
    let mn = Infinity, mx = -Infinity
    for (const v of data) { if (v < mn) mn = v; if (v > mx) mx = v }
    if (zeroBased) {
      // Magnitude series (power, bandwidth, counts): the question is "how much
      // of the maximum are we getting", so the floor is 0 and a steady value
      // reads as a flat line high in the box. Auto-scaling these to their own
      // min/max is what turned a 0.001 % ripple on a CONSTANT 171.9 kW fleet
      // harvest into a dramatic climb across the whole plot.
      mn = 0
      mx = Math.max(mx, 1e-9) * 1.08
    } else {
      if (mn === mx) { mn -= 1; mx += 1 }
      // Floor the window at 2 % of full scale so sensor noise on a flat series
      // cannot be magnified to fill the box. Without this the y-axis silently
      // becomes a microscope and every constant reads as a trend.
      const minSpan = Math.max(Math.abs(mx) * 0.02, 1e-9)
      if (mx - mn < minSpan) {
        const mid = (mx + mn) / 2
        mn = mid - minSpan / 2; mx = mid + minSpan / 2
      }
      const pad = (mx - mn) * 0.1
      mn = Math.max(0, mn - pad); mx += pad
    }
    const pts = data.map((v, i) => {
      const x = (i / (n - 1)) * 100
      const y = 100 - ((v - mn) / (mx - mn)) * 100
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    return { path: `M ${pts.join(' L ')}`, lo: mn, hi: mx }
  }, [data, zeroBased])

  return (
    <div
      ref={boxRef}
      data-dense={dense ? 'true' : undefined}
      className={
        'flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border-weak bg-bg-inset/40 ' +
        (dense ? 'px-1.5 pb-0.5 pt-1' : 'px-2 pb-1 pt-1.5')
      }
    >
      <div className="flex shrink-0 items-baseline justify-between gap-2">
        <span className={'min-w-0 truncate uppercase tracking-[0.10em] text-text-md ' +
                         (dense ? 'text-[9px]' : 'text-[10px]')}>
          {dense ? (short ?? title) : title}
        </span>
        <span className="flex shrink-0 items-baseline gap-1.5 whitespace-nowrap">
          <span className="tabular text-text-hi">
            <span className={'font-semibold ' + (dense ? 'text-[11px]' : 'text-[13px]')}>
              {current.toFixed(digits)}
            </span>
            {unit && <span className="ml-0.5 text-[9px] text-text-lo">{unit}</span>}
          </span>
          {sub && <span className="text-[9px] tabular text-text-lo">{sub}</span>}
          {dense && foot && <span className="text-[9px] tabular text-text-lo">{foot}</span>}
        </span>
      </div>
      <div className="relative min-h-0 flex-1">
        <div className="pointer-events-none absolute right-0 top-0 text-[8px] tabular text-text-lo">{hi.toFixed(axisDigits)}</div>
        <div className="pointer-events-none absolute right-0 bottom-0 text-[8px] tabular text-text-lo">{lo.toFixed(axisDigits)}</div>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
          {(dense ? [50] : [25, 50, 75]).map((p) => (
            <line key={p} x1={0} x2={100} y1={p} y2={p} stroke={colors.text.md} strokeWidth={0.4}
                  vectorEffect="non-scaling-stroke" opacity={0.15} strokeDasharray="2 3" />
          ))}
          {path && (
            <path d={path} fill="none" stroke={color} strokeWidth={2}
                  strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          )}
        </svg>
      </div>
      {!dense && (
        <div className="mt-0.5 flex shrink-0 justify-between text-[8px] tabular text-text-lo">
          <span>-{data.length}s</span>
          {foot && <span>{foot}</span>}
          <span>now</span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Solar histogram — collection (W) per collection-factor bin, the factor
// being eclipse fraction × attitude-dependent panel incidence: exactly the
// per-satellite term the fleet power model sums, so a dawn-dusk fleet reads
// full instead of empty and an eclipsed sat sits in bin 0. Header and
// axis row never shrink, the bar area absorbs whatever height is left and
// imposes no minimum of its own; under DENSE_H the axis row folds away so the
// bars keep a usable share of a starved slot.
// ---------------------------------------------------------------------------
export function SolarHistogram({ gt }: { gt: GroundTargetState | null }) {
  const [boxRef, dense] = useDenseBox<HTMLDivElement>()
  const live = gt?.enabled === true
  const bins = live && gt ? gt.solar_hist : []
  const maxColl = Math.max(1, ...bins.map((b) => b.collection_w))
  const totalColl = bins.reduce((a, b) => a + b.collection_w, 0)
  const litSats = bins.filter((b) => b.lo > 0).reduce((a, b) => a + b.sat_count, 0)

  return (
    <div ref={boxRef} className="flex min-h-0 flex-1 flex-col overflow-hidden"
         data-testid="solar-histogram" data-state={live ? 'live' : 'empty'}
         data-dense={dense ? 'true' : undefined}>
      {!live || !gt ? (
        <EmptyHint>Mark the ground station to chart per-satellite solar collection.</EmptyHint>
      ) : (
        <>
          <div className={'flex shrink-0 items-baseline justify-between gap-2 ' +
                          (dense ? 'mb-0.5' : 'mb-1')}>
            <span className={'min-w-0 truncate uppercase tracking-[0.10em] text-text-md ' +
                             (dense ? 'text-[9px]' : 'text-[10px]')}>
              {dense ? `Solar · bin ${gt.solar_bin}` : `Solar collection · bin ${gt.solar_bin}`}
            </span>
            <span className={'shrink-0 tabular text-text-lo ' + (dense ? 'text-[9px]' : 'text-[10px]')}>
              {(totalColl / 1000).toFixed(1)} kW · {litSats} lit
            </span>
          </div>
          <div className={'flex min-h-0 flex-1 rounded-md border border-border-weak bg-bg-inset/40 ' +
                          (dense ? 'gap-px p-1' : 'gap-[2px] p-1.5')}>
            {bins.map((b) => {
              const h = (b.collection_w / maxColl) * 100
              return (
                // h-full on the column so the bar's percentage height resolves
                // against the panel height (an auto-height column collapses it).
                <div key={b.lo} className="group relative flex h-full min-w-0 flex-1 flex-col justify-end">
                  <div
                    className="w-full rounded-sm"
                    style={{
                      height: `${Math.max(b.collection_w > 0 ? 2 : 0, h)}%`,
                      background: SOLAR_HUE,
                      opacity: 0.35 + 0.65 * (b.lo / 100),
                    }}
                    title={`${b.lo}–${b.hi} collection · ${b.sat_count} sats · ${Math.round(b.collection_w)} W`}
                  />
                  {b.sat_count > 0 && !dense && (
                    <span className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 text-[7px] tabular text-text-lo opacity-0 group-hover:opacity-100">
                      {b.sat_count}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          {!dense && (
            <div className="mt-0.5 flex shrink-0 justify-between text-[8px] tabular text-text-lo">
              <span>0</span>
              <span>collection factor (attitude × sun × eclipse) →</span>
              <span>100</span>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Energy harvest — fleet-wide solar collection over the rolling window. Unlike
// the histogram this covers the WHOLE constellation, counts eclipse, and needs
// NO ground target: when nothing is marked the panel can hand it the entire
// Solar tab and it simply fills the box.
// ---------------------------------------------------------------------------
export function EnergyHarvestChart({ history }: { history: EnergySample[] }) {
  // Cumulative energy: one sample = one sim second = `sampleRealS` real
  // seconds of collection. W·s → kWh.
  const timeScale = useTelemetryStore((st) => st.constellationDetail?.time_scale)
  const sampleRealS =
    typeof timeScale === 'number' && Number.isFinite(timeScale) && timeScale > 0
      ? timeScale
      : FALLBACK_SAMPLE_REAL_S
  const kwh = useMemo(
    () => (history.reduce((a, s) => a + s.w, 0) * sampleRealS) / 3_600_000,
    [history, sampleRealS],
  )
  const series = useMemo(() => history.map((s) => s.w / 1000), [history])
  const last = history.length ? history[history.length - 1] : null

  return (
    <div className="flex min-h-0 flex-1 flex-col"
         data-testid="energy-harvest" data-state={last === null ? 'empty' : 'live'}>
      {last === null ? (
        <EmptyHint>Waiting for fleet telemetry…</EmptyHint>
      ) : (
        <LineChart
          title="Energy harvest · constellation"
          short="Harvest"
          data={series}
          current={last.w / 1000}
          unit="kW"
          color={colors.ok}
          digits={2}
          axisDigits={1}
          zeroBased
          sub={`${kwh.toFixed(2)} kWh`}
          foot={`${last.lit} lit`}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Solar-bin width — the histogram's binning control (Solar tab header).
// ---------------------------------------------------------------------------
export function SolarBinControl({ value, onChange }: {
  value: number; onChange: (n: number) => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-2">
      <span className="flex w-[92px] shrink-0 items-center gap-1 text-[10px] text-text-md">
        <Sun size={10} /> Solar bin
      </span>
      <div className="flex flex-1 gap-1">
        {[5, 10].map((n) => (
          <button
            key={n}
            type="button"
            data-testid={`solar-bin-${n}`}
            onClick={() => onChange(n)}
            aria-pressed={value === n}
            className={
              'flex-1 rounded border px-1 py-0.5 text-[9px] ' +
              (value === n
                ? 'border-accent bg-bg-card-hi text-text-hi'
                : 'border-border-weak bg-bg-inset/40 text-text-lo hover:border-border-med')
            }
          >
            per {n}
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Ground station — mark toggle · elevation mask · comms band, the live
// visibility readout and the one-orbit pass analysis. Lives next to the charts
// it drives (Coverage tab).
//
// `compact` re-lays the SAME controls into three dense rows with no section
// header, handing the saved height back to the map and the charts below. It
// removes no control: the analyze button and the pass strip stay, just smaller.
// ---------------------------------------------------------------------------
export function GroundStationControls({ design, compact = false }: {
  design: ReturnType<typeof useOrbitDesign>
  /** true → the dense three-row layout (same controls, no section header). */
  compact?: boolean
}): JSX.Element {
  const { bands, groundTarget, visibility, analyzing, setGroundTarget, analyze } = design
  const gtOn = groundTarget?.enabled === true

  // Local config draft, authoritative for the controls while the user edits.
  const [cfg, setCfg] = useState<GroundConfig>(GROUND_CONFIG_DEFAULTS)
  // Debounce the live re-config POST: the elevation slider fires onChange on
  // every pixel of a drag, which would otherwise flood the backend with
  // /ground_target posts (and race — last-write-wins is not guaranteed).
  const postTimer = useRef<number | undefined>(undefined)
  const pendingRef = useRef(false)
  useEffect(() => () => window.clearTimeout(postTimer.current), [])

  // Adopt the server config whenever it changes AND we have no local edit in
  // flight — keeps the selector in sync with the live analytics (e.g. after an
  // external POST /ground_target, or the Solar tab's bin control) without
  // stomping an in-progress drag.
  useEffect(() => {
    if (!groundTarget?.enabled || pendingRef.current) return
    setCfg({
      elevation_mask_deg: groundTarget.elevation_mask_deg,
      band: groundTarget.band,
      solar_bin: groundTarget.solar_bin,
    })
  }, [groundTarget?.enabled, groundTarget?.band,
      groundTarget?.elevation_mask_deg, groundTarget?.solar_bin])

  const bandList = bands.length ? bands : FALLBACK_BANDS
  const push = (next: GroundConfig) => {
    setCfg(next)
    if (!gtOn) return
    pendingRef.current = true
    window.clearTimeout(postTimer.current)
    postTimer.current = window.setTimeout(() => {
      void setGroundTarget(true, next).finally(() => { pendingRef.current = false })
    }, 200)
  }

  // The selected band can raise the effective mask above the slider (Ka needs
  // 20°). The full layout prints that on its own line; the compact one folds it
  // into the slider readout as "5→20°" rather than spending a row on it.
  const effectiveMask = gtOn && groundTarget ? groundTarget.min_elevation_deg : cfg.elevation_mask_deg
  const maskClamped = effectiveMask > cfg.elevation_mask_deg + 0.5

  const toggleBtn = (
    <button
      type="button"
      data-testid="ground-target-toggle"
      onClick={() => void setGroundTarget(!gtOn, cfg)}
      aria-pressed={gtOn}
      className={
        (compact
          ? 'flex min-w-0 flex-1 items-center gap-1.5 rounded border px-1.5 py-1 text-left text-[10px] '
          : 'mb-2 flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-[11px] ') +
        (gtOn ? 'border-err/60 bg-err/15 text-text-hi'
              : 'border-border-weak bg-bg-inset/40 text-text-md hover:border-border-med')
      }
    >
      {compact
        ? <MapPin size={10} className={'shrink-0 ' + (gtOn ? 'text-err' : 'text-text-lo')} />
        : <span className={'h-2 w-2 shrink-0 rounded-full ' + (gtOn ? 'bg-err' : 'border border-border-med')} />}
      <span className="truncate">
        {compact
          ? (gtOn ? 'Singapore · marked' : 'Mark Singapore')
          : (gtOn ? 'Marked on Earth — 1.35°N 103.82°E' : 'Mark Singapore on the Earth')}
      </span>
    </button>
  )

  const bandChips = (
    <div className="flex min-w-0 flex-1 gap-1">
      {bandList.map((b) => (
        <button
          key={b.id}
          type="button"
          data-testid={`band-${b.id}`}
          onClick={() => push({ ...cfg, band: b.id })}
          aria-pressed={cfg.band === b.id}
          title={`${b.label} · ${b.per_sat_mbps} Mbps/sat · min ${b.min_elevation_deg}°`}
          className={
            'min-w-0 flex-1 rounded border px-1 text-[9px] ' + (compact ? 'py-px ' : 'py-0.5 ') +
            (cfg.band === b.id
              ? 'border-accent bg-bg-card-hi text-text-hi'
              : 'border-border-weak bg-bg-inset/40 text-text-lo hover:border-border-med')
          }
        >
          {b.id}
        </button>
      ))}
    </div>
  )

  const analyzeBtn = (
    <button
      type="button"
      data-testid="ground-analyze"
      onClick={() => void analyze()}
      disabled={analyzing}
      title="Analyze passes · 1 orbit"
      aria-label="Analyze passes over one orbit"
      className={
        'flex items-center gap-1.5 rounded border border-border-med bg-bg-inset/40 ' +
        'uppercase tracking-[0.08em] text-text-md hover:text-text-hi disabled:opacity-40 ' +
        (compact ? 'shrink-0 px-1.5 py-px text-[9px]' : 'justify-center px-2 py-1 text-[10px]')
      }
    >
      {analyzing && <Loader2 size={compact ? 9 : 10} className="animate-spin" />}
      {compact ? 'Passes' : 'Analyze passes · 1 orbit'}
    </button>
  )

  if (compact) {
    return (
      <div
        data-testid="ground-station-controls"
        data-compact="true"
        className="flex shrink-0 flex-col gap-1 rounded-lg border border-border-weak bg-bg-inset/30 px-2 py-1.5"
      >
        {/* Row 1 — mark toggle + the live readout that used to sit two rows down. */}
        <div className="flex items-center gap-1.5">
          {toggleBtn}
          {gtOn && groundTarget && (
            <span
              data-testid="ground-visibility-live"
              className={'shrink-0 tabular text-[10px] font-semibold ' +
                         (groundTarget.visible_sats > 0 ? 'text-ok' : 'text-text-lo')}
            >
              {groundTarget.visible_sats > 0
                ? `${groundTarget.visible_sats} sat · ${Math.round(groundTarget.aggregate_mbps)} Mbps`
                : 'no contact'}
            </span>
          )}
        </div>

        {/* Row 2 — elevation mask. */}
        <div className="flex items-center gap-1.5">
          <span className="w-[34px] shrink-0 text-[9px] uppercase tracking-[0.08em] text-text-lo">Mask</span>
          <input
            type="range" min={0} max={40} step={1} value={cfg.elevation_mask_deg}
            aria-label="Elevation mask"
            onChange={(e) => push({ ...cfg, elevation_mask_deg: Number(e.target.value) })}
            className="h-1 min-w-0 flex-1 accent-accent"
          />
          <span className="w-[46px] shrink-0 text-right text-[9px] tabular text-text-hi"
                title={maskClamped ? 'The selected band raises the effective mask' : undefined}>
            {cfg.elevation_mask_deg.toFixed(0)}
            {maskClamped && <span className="text-warn">→{effectiveMask.toFixed(0)}</span>}°
          </span>
        </div>

        {/* Row 3 — comms band + the one-orbit pass analysis trigger. */}
        <div className="flex items-center gap-1.5">
          <span className="w-[34px] shrink-0 text-[9px] uppercase tracking-[0.08em] text-text-lo">Band</span>
          {bandChips}
          {gtOn && analyzeBtn}
        </div>

        {gtOn && visibility && <PassAnalysis v={visibility} compact />}
      </div>
    )
  }

  return (
    <Section icon={<MapPin size={11} className="text-err" />} title="Ground station · Singapore"
             testId="ground-station-controls">
      {toggleBtn}

      {/* Config: elevation mask · comms band. (Solar bin sits on the Solar tab.) */}
      <Field label="Elevation mask" unit="°" value={cfg.elevation_mask_deg} min={0} max={40} step={1} digits={0}
             onChange={(v) => push({ ...cfg, elevation_mask_deg: v })} />

      <div className="mt-1 flex items-center gap-2">
        <span className="flex w-[92px] shrink-0 items-center gap-1 text-[10px] text-text-md">
          <Radio size={10} /> Comms band
        </span>
        {bandChips}
      </div>
      {gtOn && groundTarget && (
        <div className="mt-0.5 text-[9px] text-text-lo tabular">
          {groundTarget.band_label} · {groundTarget.band_mbps_per_sat} Mbps/sat ·
          effective mask {groundTarget.min_elevation_deg.toFixed(0)}°
        </div>
      )}

      {gtOn && groundTarget && (
        <div className="mt-2 flex flex-col gap-1.5" data-testid="ground-visibility-live">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-text-md">Comm visibility now</span>
            <span className={'tabular font-semibold ' + (groundTarget.visible_sats > 0 ? 'text-ok' : 'text-text-lo')}>
              {groundTarget.visible_sats > 0
                ? `${groundTarget.visible_sats} sat${groundTarget.visible_sats > 1 ? 's' : ''} · ${Math.round(groundTarget.aggregate_mbps)} Mbps`
                : 'no contact'}
            </span>
          </div>
          {analyzeBtn}
          {visibility && <PassAnalysis v={visibility} />}
        </div>
      )}
    </Section>
  )
}

const FALLBACK_BANDS: CommsBand[] = [
  { id: 'UHF', label: 'UHF', per_sat_mbps: 2, min_elevation_deg: 5 },
  { id: 'S', label: 'S-band', per_sat_mbps: 20, min_elevation_deg: 5 },
  { id: 'X', label: 'X-band', per_sat_mbps: 150, min_elevation_deg: 10 },
  { id: 'Ka', label: 'Ka-band', per_sat_mbps: 800, min_elevation_deg: 20 },
]

// ---------------------------------------------------------------------------
function PassAnalysis({ v, compact = false }: {
  v: ReturnType<typeof useOrbitDesign>['visibility'] & object
  /** true → thinner strip and one merged caption line. */
  compact?: boolean
}) {
  if (!v) return null
  const toRealMin = (simS: number) => (simS * v.time_scale) / 60
  const nextIn = v.next_pass_in_s !== null && v.next_pass_in_s > 0.5
    ? `${toRealMin(v.next_pass_in_s).toFixed(0)} min`
    : null
  const passes = `${v.windows.length} pass${v.windows.length === 1 ? '' : 'es'}`

  return (
    <div data-testid="ground-passes"
         className={'rounded border border-border-weak bg-bg-inset/40 ' + (compact ? 'p-1' : 'p-1.5')}>
      <div className={'relative w-full overflow-hidden rounded-sm bg-bg-app ' + (compact ? 'h-1.5' : 'h-2')}>
        {v.windows.map((w, i) => (
          <span key={i} className="absolute inset-y-0 bg-ok/80"
                style={{ left: `${(w.start_s / v.duration_s) * 100}%`,
                         width: `${Math.max(1, ((w.end_s - w.start_s) / v.duration_s) * 100)}%` }} />
        ))}
      </div>
      {compact ? (
        <div className="mt-0.5 flex items-baseline justify-between gap-2 text-[9px] tabular text-text-lo">
          <span className="min-w-0 truncate text-text-md">
            contact {Math.round(v.coverage_fraction * 100)}% · {passes}
            {nextIn && <> · next {nextIn}</>}
          </span>
          <span className="shrink-0">1 orbit · {(v.period_s_real / 60).toFixed(0)} min</span>
        </div>
      ) : (
        <>
          <div className="mt-1 flex justify-between text-[9px] tabular text-text-lo">
            <span>now</span><span>+{(v.period_s_real / 60).toFixed(0)} min (1 orbit)</span>
          </div>
          <div className="mt-1 text-[10px] tabular text-text-md">
            contact {Math.round(v.coverage_fraction * 100)}% of orbit · {passes}
            {nextIn && <> · next in {nextIn}</>}
          </div>
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Local chrome — kept private here so the analytics file carries no dependency
// on the designer panel's layout helpers.
// ---------------------------------------------------------------------------
function Section({ icon, title, testId, children }: {
  icon: React.ReactNode; title: string; testId?: string; children: React.ReactNode
}) {
  return (
    <div data-testid={testId}
         className="shrink-0 rounded-lg border border-border-weak bg-bg-inset/30 px-2 py-1.5">
      <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.10em] text-text-lo">
        <span className="text-accent">{icon}</span>{title}
      </div>
      {children}
    </div>
  )
}

function Field({ label, unit, value, min, max, step, digits = 0, onChange }: {
  label: string; unit: string; value: number
  min: number; max: number; step: number; digits?: number
  onChange: (v: number) => void
}) {
  return (
    <div className="mb-1 flex items-center gap-2">
      <span className="w-[92px] shrink-0 text-[10px] text-text-md">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="h-1 flex-1 accent-accent" />
      <span className="w-[64px] shrink-0 text-right text-[10px] tabular text-text-hi">
        {value.toFixed(digits)}{unit && <span className="text-text-lo"> {unit}</span>}
      </span>
    </div>
  )
}
