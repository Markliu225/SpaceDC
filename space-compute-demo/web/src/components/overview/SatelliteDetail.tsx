import { useMemo, type ReactNode } from 'react'
import { Card, Num } from '../primitives'
import { useFleetStatuses, type FleetSat } from '../../hooks/useFleetStatuses'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { SatelliteSelector } from './SatelliteSelector'

type Tone = 'ok' | 'warn' | 'err' | 'hi'

const TONE_CLS: Record<Tone, string> = {
  hi:   'text-text-hi',
  ok:   'text-ok',
  warn: 'text-warn',
  err:  'text-err',
}

/** Inline param chip — label and value sit side-by-side with a 6px gap, so
 *  ORBIT and LEO read as a paired phrase. The chips are then dropped into a
 *  flex-wrap row that packs them tight (vs the previous 4-col grid, which
 *  stretched every cell to ~200px and left huge gaps between adjacent
 *  pairs at this card's full-width footprint). */
function Param({
  label, value, unit, digits, tone = 'hi',
}: {
  label: string
  value: number | string
  unit?: string
  digits?: number
  tone?: Tone
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-[10px] uppercase tracking-[0.08em] text-text-lo">{label}</span>
      <Num
        value={value}
        digits={digits ?? 0}
        className={`text-[13px] ${TONE_CLS[tone]}`}
      />
      {unit && <span className="text-[10px] text-text-lo">{unit}</span>}
    </span>
  )
}

/** String-value sibling of <Param />. */
function ParamText({
  label, value, tone = 'hi',
}: { label: string; value: ReactNode; tone?: Tone }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-[10px] uppercase tracking-[0.08em] text-text-lo">{label}</span>
      <span className={`text-[13px] ${TONE_CLS[tone]}`}>{value}</span>
    </span>
  )
}

interface Bar {
  label: string
  value: number
  digits: number
  unit: string
  pct: number
  tone?: 'ok' | 'warn' | 'err'
}

const GPU_CYCLE = ['H100', 'H200', 'B200', 'MI300X'] as const
const TASK_PHASES = ['idle', 'created', 'capturing', 'inferencing', 'packaging', 'downlink', 'delivered'] as const

/** Derive the per-sat virtual telemetry from the live fleet sat + sim time.
 *
 *  This mirrors `useMockTelemetryFeed` but works for ANY index, not just
 *  the seed 24 list — we don't store per-sat telemetry in the store any
 *  more (would explode memory at Starlink scale), so we synthesise on
 *  demand from `idx`, `sim_time_s`, `status`, and `sunlit`. */
function deriveTelemetry(sat: FleetSat | undefined, simTimeS: number) {
  if (!sat) {
    return null
  }
  const phase = sat.idx
  const gpu   = GPU_CYCLE[sat.idx % 4]
  const util  = sat.status === 'online'
    ? Math.max(0, 0.45 + 0.35 * Math.sin(simTimeS / 12 + phase * 0.4))
    : 0
  const payloadPwr  = sat.status === 'online' ? 420 + 1700 * util : 0
  const platformPwr = sat.status === 'offline' ? 0 : 600
  const solarIn = sat.status === 'offline'
    ? 0
    : sat.sunlit
      ? 4200
      : 0
  const temp = sat.status === 'online'
    ? 56 + 18 * util
    : sat.status === 'eclipse'
      ? 32
      : sat.status === 'standby'
        ? 28
        : 18
  const socBase = sat.status === 'offline' ? 0.06 : 0.78 - (sat.idx % 6) * 0.05
  const socDrift = sat.status === 'online' && util > 0.55 ? -0.02 : 0.01
  const soc = Math.max(0, Math.min(1, socBase + socDrift * Math.sin(simTimeS / 30 + phase)))
  // Downlink only flows when this sat happens to be over a ground station —
  // approximated by being sunlit AND every 3rd online sat at any time.
  const downlink = sat.status === 'online' && sat.idx % 3 === 0
    ? 120 + 12 * Math.sin(simTimeS / 4 + phase)
    : 0
  const taskState = sat.status === 'online'
    ? TASK_PHASES[(Math.floor(simTimeS / 8) + sat.idx) % TASK_PHASES.length]
    : 'idle' as const
  return {
    gpu, util, payloadPwr, platformPwr, solarIn, temp, soc, downlink, taskState,
  }
}

/** Pick orbit category from altitude — same buckets backend uses. */
function orbitTypeFromAlt(altKm: number): 'LEO' | 'SSO' | 'MEO' | 'GEO' {
  // Treat sun-sync (polar high-inc LEO) as SSO when the constellation is
  // explicitly polar; otherwise fall back to LEO.
  if (altKm < 2000) return 'LEO'
  if (altKm < 35000) return 'MEO'
  return 'GEO'
}

/**
 * SatelliteDetail — full 14-parameter readout + 4 progress bars for the
 * currently-selected sat. Works for any sat in the fleet (the legacy
 * `SelectedSatellite` only worked for the 24 seed sats).
 *
 * Layout (similar to the old SelectedSatellite but no decorative icon):
 *   ┌─────────────────────────────────────────────────────────┐
 *   │ Selected Satellite: SAT-XX                              │
 *   ├──────────────────────────────┬──────────────────────────┤
 *   │ 4 × 4 param grid             │ 4 vertical metric bars   │
 *   │ (14 params)                  │ (util / soc / temp / dl) │
 *   └──────────────────────────────┴──────────────────────────┘
 */
export function SatelliteDetail() {
  const fleet       = useFleetStatuses()
  const selectedIdx = useTelemetryStore((s) => s.selectedSatIdx)
  const simTimeS    = useTelemetryStore((s) => s.sim_time_s)
  const detail      = useTelemetryStore((s) => s.constellationDetail)

  const sat = fleet[selectedIdx]
  const tele = useMemo(() => deriveTelemetry(sat, simTimeS), [sat, simTimeS])

  if (!sat || !tele) {
    return (
      <Card selected className="h-full flex items-center justify-center min-h-0">
        <span className="text-[12px] text-text-lo">
          {fleet.length === 0 ? 'Loading constellation…' : 'No sat selected.'}
        </span>
      </Card>
    )
  }

  const orbitType = orbitTypeFromAlt(sat.altitudeKm)

  // GPU Util / Battery / Temp move out of the param row and become a horizontal
  // 3-up bar strip below the params. Downlink is dropped entirely — it duplicated
  // the GS-Visible chip and ate space we'd rather give to the bars.
  const bars: Bar[] = [
    { label: 'GPU Util', value: tele.util * 100, digits: 0, unit: '%',    pct: tele.util },
    { label: 'Battery',  value: tele.soc * 100,  digits: 0, unit: '%',    pct: tele.soc,
      tone: tele.soc < 0.3 ? 'err' : tele.soc < 0.5 ? 'warn' : undefined },
    { label: 'Temp',     value: tele.temp,       digits: 1, unit: '°C',
      pct: Math.min(1, Math.max(0, (tele.temp - 20) / 60)),
      tone: tele.temp > 70 ? 'err' : tele.temp > 50 ? 'warn' : undefined },
  ]

  return (
    <Card
      dense
      selected
      className="h-full flex flex-col min-h-0 overflow-visible relative z-20"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
            Selected Satellite
          </span>
          <SatelliteSelector />
        </div>
        <div className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          {detail?.name ?? '—'} · plane {sat.planeIdx + 1}/{detail?.planes ?? '—'}
        </div>
      </div>

      <div className="mt-0.5 flex flex-1 min-h-0 flex-col gap-1.5">
        {/* Param chips — static / slow-changing fields. */}
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <ParamText label="Orbit"        value={orbitType} />
          <ParamText label="GPU"          value={tele.gpu} />
          <ParamText label="Sunlit"       value={sat.sunlit ? 'YES' : 'NO'} tone={sat.sunlit ? 'ok' : 'warn'} />
          <ParamText label="GS Visible"   value={tele.downlink > 0 ? 'YES' : 'NO'} tone={tele.downlink > 0 ? 'ok' : 'hi'} />
          <ParamText label="Lat / Lon"    value={`${sat.lat.toFixed(1)} / ${sat.lon.toFixed(1)}°`} />
          <Param     label="Altitude"     value={sat.altitudeKm} digits={0} unit="km" />
          <Param     label="Solar In"     value={tele.solarIn} digits={0} unit="W" />
          <Param     label="Platform Pwr" value={tele.platformPwr} digits={0} unit="W" />
          <Param     label="Payload Pwr"  value={tele.payloadPwr} digits={0} unit="W" />
          <ParamText label="Task"         value={tele.taskState} />
        </div>

        {/* Dynamic bars — 3 columns, each occupying ~1/3 of the panel width. */}
        <div className="grid grid-cols-3 gap-3">
          {bars.map((b) => <MetricBar key={b.label} bar={b} />)}
        </div>
      </div>
    </Card>
  )
}

function MetricBar({ bar }: { bar: Bar }) {
  const fillBg =
    bar.tone === 'err'  ? 'linear-gradient(90deg, #EF4444 0%, #FCA5A5 100%)' :
    bar.tone === 'warn' ? 'linear-gradient(90deg, #F59E0B 0%, #FDE68A 100%)' :
                          'linear-gradient(90deg, #3B9EFF 0%, #E0EEFF 100%)'
  const shadow =
    bar.tone === 'err'  ? '0 0 6px rgba(239,68,68,0.45)' :
    bar.tone === 'warn' ? '0 0 6px rgba(245,158,11,0.45)' :
                          '0 0 6px rgba(59,158,255,0.45)'
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.08em] text-text-lo">{bar.label}</span>
        <span className="flex items-baseline">
          <Num value={bar.value} digits={bar.digits} className="text-[12px] text-text-hi" />
          <span className="ml-1 text-[10px] text-text-lo">{bar.unit}</span>
        </span>
      </div>
      <div className="mt-0.5 h-1 w-full overflow-hidden rounded-full bg-bg-inset">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${Math.round(bar.pct * 100)}%`, background: fillBg, boxShadow: shadow }}
        />
      </div>
    </div>
  )
}
