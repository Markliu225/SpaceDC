import { useMemo } from 'react'
import type { CommsBand, GroundTargetState } from '../../types/messages'
import type { CoverageSample } from '../../hooks/useOrbitDesign'
import { COMPARE_PALETTE } from '../twin/comparePalette'
import { colors } from '../../design/tokens'

/**
 * Ground-station analytics charts for the Overview panel, all driven by the
 * live StatePacket.ground_target:
 *   - CoverageCharts — visible-sat count + aggregate bandwidth over time
 *   - SolarHistogram — solar-collection per illumination-intensity bin
 *   - BandCurves     — aggregate throughput vs elevation mask, one line per
 *                      comms band (the band tradeoff)
 */

// Series hues come from the token palette: solar = the desaturated amber
// ribbon (data hue, not the warn status), visible-sat count = the app accent.
const SOLAR_HUE = colors.ribbons[2]
const VISIBLE_HUE = colors.accent

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center rounded border border-dashed
                    border-border-weak px-3 text-center text-[11px] text-text-faint">
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Coverage — two stacked line charts (no dual-axis): visible sats + Mbps.
// ---------------------------------------------------------------------------
export function CoverageCharts({ history, gt }: {
  history: CoverageSample[]; gt: GroundTargetState | null
}) {
  if (!gt?.enabled) {
    return <EmptyHint>Mark the ground station (Orbit Designer tab) to chart visibility over time.</EmptyHint>
  }
  return (
    <div className="flex flex-1 min-h-0 flex-col gap-2" data-testid="coverage-charts">
      <LineChart
        title="Visible satellites"
        data={history.map((s) => s.visible)}
        current={gt.visible_sats}
        unit=""
        color={VISIBLE_HUE}
        digits={0}
      />
      <LineChart
        title={`Aggregate bandwidth · ${gt.band_label}`}
        data={history.map((s) => s.mbps)}
        current={gt.aggregate_mbps}
        unit="Mbps"
        color={SOLAR_HUE}
        digits={0}
      />
    </div>
  )
}

function LineChart({ title, data, current, unit, color, digits }: {
  title: string; data: number[]; current: number
  unit: string; color: string; digits: number
}) {
  const { path, lo, hi } = useMemo(() => {
    const n = data.length
    if (n < 2) return { path: '', lo: 0, hi: 1 }
    let mn = Infinity, mx = -Infinity
    for (const v of data) { if (v < mn) mn = v; if (v > mx) mx = v }
    if (mn === mx) { mn -= 1; mx += 1 }
    const pad = (mx - mn) * 0.1
    mn = Math.max(0, mn - pad); mx += pad
    const pts = data.map((v, i) => {
      const x = (i / (n - 1)) * 100
      const y = 100 - ((v - mn) / (mx - mn)) * 100
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    return { path: `M ${pts.join(' L ')}`, lo: mn, hi: mx }
  }, [data])

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-md border border-border-weak bg-bg-inset/40 px-2 pb-1 pt-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-md">{title}</span>
        <span className="tabular text-text-hi">
          <span className="text-[13px] font-semibold">{current.toFixed(digits)}</span>
          {unit && <span className="ml-0.5 text-[9px] text-text-lo">{unit}</span>}
        </span>
      </div>
      <div className="relative flex-1 min-h-0">
        <div className="pointer-events-none absolute right-0 top-0 text-[8px] tabular text-text-lo">{hi.toFixed(0)}</div>
        <div className="pointer-events-none absolute right-0 bottom-0 text-[8px] tabular text-text-lo">{lo.toFixed(0)}</div>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
          {[25, 50, 75].map((p) => (
            <line key={p} x1={0} x2={100} y1={p} y2={p} stroke={colors.text.md} strokeWidth={0.4}
                  vectorEffect="non-scaling-stroke" opacity={0.15} strokeDasharray="2 3" />
          ))}
          {path && (
            <path d={path} fill="none" stroke={color} strokeWidth={2}
                  strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          )}
        </svg>
      </div>
      <div className="mt-0.5 flex justify-between text-[8px] tabular text-text-lo">
        <span>-{data.length}s</span><span>now</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Solar histogram — collection (W) per illumination-intensity bin.
// ---------------------------------------------------------------------------
export function SolarHistogram({ gt }: { gt: GroundTargetState | null }) {
  if (!gt?.enabled) {
    return <EmptyHint>Mark the ground station to chart per-satellite solar collection.</EmptyHint>
  }
  const bins = gt.solar_hist
  const maxColl = Math.max(1, ...bins.map((b) => b.collection_w))
  const totalColl = bins.reduce((a, b) => a + b.collection_w, 0)
  const litSats = bins.filter((b) => b.lo > 0).reduce((a, b) => a + b.sat_count, 0)

  return (
    <div className="flex flex-1 min-h-0 flex-col" data-testid="solar-histogram">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-md">
          Solar collection · bin {gt.solar_bin}
        </span>
        <span className="text-[10px] tabular text-text-lo">
          {(totalColl / 1000).toFixed(1)} kW · {litSats} lit
        </span>
      </div>
      <div className="flex flex-1 min-h-0 gap-[2px] rounded-md border border-border-weak bg-bg-inset/40 p-1.5">
        {bins.map((b) => {
          const h = (b.collection_w / maxColl) * 100
          return (
            // h-full on the column so the bar's percentage height resolves
            // against the panel height (an auto-height column collapses it).
            <div key={b.lo} className="group relative flex h-full flex-1 flex-col justify-end">
              <div
                className="w-full rounded-sm"
                style={{
                  height: `${Math.max(b.collection_w > 0 ? 2 : 0, h)}%`,
                  background: SOLAR_HUE,
                  opacity: 0.35 + 0.65 * (b.lo / 100),
                }}
                title={`${b.lo}–${b.hi} intensity · ${b.sat_count} sats · ${Math.round(b.collection_w)} W`}
              />
              {b.sat_count > 0 && (
                <span className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 text-[7px] tabular text-text-lo opacity-0 group-hover:opacity-100">
                  {b.sat_count}
                </span>
              )}
            </div>
          )
        })}
      </div>
      <div className="mt-0.5 flex justify-between text-[8px] tabular text-text-lo">
        <span>0</span>
        <span>solar illumination intensity →</span>
        <span>100</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Band curves — aggregate throughput (log) vs elevation mask, one per band.
// ---------------------------------------------------------------------------
export function BandCurves({ gt, bands }: {
  gt: GroundTargetState | null; bands: CommsBand[]
}) {
  const cdf = gt?.elevation_cdf ?? []
  const model = useMemo(() => {
    if (!gt?.enabled || cdf.length === 0 || bands.length === 0) return null
    const masks = cdf.map((c) => c.mask_deg)
    const maxMask = masks[masks.length - 1] || 40
    const countAt = (m: number) => cdf.find((c) => c.mask_deg === m)?.count ?? 0
    // Throughput floor/ceiling for the log axis.
    let hi = 1
    for (const band of bands) {
      for (const c of cdf) {
        if (c.mask_deg >= band.min_elevation_deg) hi = Math.max(hi, c.count * band.per_sat_mbps)
      }
    }
    const loLog = 0                       // log10(1)
    const hiLog = Math.log10(Math.max(10, hi))
    const yOf = (mbps: number) => {
      const l = Math.log10(Math.max(1, mbps))
      return 100 - ((l - loLog) / (hiLog - loLog)) * 100
    }
    const xOf = (m: number) => (m / maxMask) * 100
    const curves = bands.map((band, i) => {
      const pts: string[] = []
      for (const c of cdf) {
        if (c.mask_deg < band.min_elevation_deg) continue
        pts.push(`${xOf(c.mask_deg).toFixed(2)},${yOf(c.count * band.per_sat_mbps).toFixed(2)}`)
      }
      // Operating point = throughput at the effective mask. For the ACTIVE
      // band use the exact backend aggregate (the effective mask can be a
      // non-grid value, e.g. 12°, that the CDF's 5° grid would snap down);
      // other bands read the grid count at their own minimum mask.
      const active = band.id === gt.band
      const opMask = Math.max(gt.min_elevation_deg, band.min_elevation_deg)
      const opMbps = active
        ? gt.aggregate_mbps
        : countAt(masks.reduce((best, m) => (m <= opMask && m > best ? m : best), 0))
          * band.per_sat_mbps
      return {
        band, color: COMPARE_PALETTE[i % COMPARE_PALETTE.length],
        path: pts.length >= 2 ? `M ${pts.join(' L ')}` : '',
        opX: xOf(opMask), opY: yOf(opMbps), opMbps, active,
      }
    })
    return { curves, xOf, maxMask, hi }
  }, [gt, cdf, bands])

  if (!gt?.enabled) {
    return <EmptyHint>Mark the ground station to compare communication bands.</EmptyHint>
  }
  if (!model) return <EmptyHint>Waiting for fleet data…</EmptyHint>

  return (
    <div className="flex flex-1 min-h-0 flex-col" data-testid="band-curves">
      <div className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-md">
          Throughput vs elevation mask
        </span>
        {model.curves.map((c) => (
          <span key={c.band.id} className="flex items-center gap-1 text-[9px]">
            <span className="inline-block h-[3px] w-3.5 rounded-full" style={{ background: c.color }} />
            <span className={c.active ? 'text-text-hi font-semibold' : 'text-text-md'}>{c.band.label}</span>
          </span>
        ))}
      </div>
      <div className="relative flex-1 min-h-0 rounded-md border border-border-weak bg-bg-inset/40">
        <div className="pointer-events-none absolute left-1 top-0.5 text-[8px] tabular text-text-lo">
          {(model.hi >= 1000 ? `${(model.hi / 1000).toFixed(0)}k` : model.hi.toFixed(0))} Mbps
        </div>
        <div className="pointer-events-none absolute left-1 bottom-3 text-[8px] tabular text-text-lo">1 Mbps</div>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
          {[25, 50, 75].map((p) => (
            <line key={p} x1={0} x2={100} y1={p} y2={p} stroke={colors.text.md} strokeWidth={0.4}
                  vectorEffect="non-scaling-stroke" opacity={0.15} strokeDasharray="2 3" />
          ))}
          {/* Effective-mask marker. */}
          <line x1={model.xOf(gt.min_elevation_deg)} x2={model.xOf(gt.min_elevation_deg)}
                y1={0} y2={100} stroke={colors.text.hi} strokeWidth={1} strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke" opacity={0.4} />
          {model.curves.map((c) => c.path && (
            <path key={c.band.id} d={c.path} fill="none" stroke={c.color}
                  strokeWidth={c.active ? 2.6 : 1.6} strokeLinejoin="round" strokeLinecap="round"
                  vectorEffect="non-scaling-stroke" opacity={c.active ? 1 : 0.75} />
          ))}
          {/* Operating-point dots. */}
          {model.curves.map((c) => c.opMbps > 0 && (
            <circle key={c.band.id} cx={c.opX} cy={c.opY} r={c.active ? 2.6 : 1.8}
                    fill={c.color} stroke={colors.bg.inset} strokeWidth={1} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
      </div>
      <div className="mt-0.5 flex justify-between text-[8px] tabular text-text-lo">
        <span>0°</span>
        <span>elevation mask →</span>
        <span>{model.maxMask}°</span>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5">
        {model.curves.map((c) => (
          <span key={c.band.id} className="flex items-center justify-between text-[9px] tabular">
            <span className="flex items-center gap-1 text-text-md">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: c.color }} />
              {c.band.label}
            </span>
            <span className={c.active ? 'text-text-hi' : 'text-text-lo'}>
              {c.opMbps >= 1000 ? `${(c.opMbps / 1000).toFixed(1)}G` : `${Math.round(c.opMbps)}M`}bps
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}
