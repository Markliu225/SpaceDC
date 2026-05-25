import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Num } from '../primitives'
import { SatParamsGrid } from './SatParamsGrid'
import { SatelliteIcon } from './SatelliteIcon'

interface Bar {
  label: string
  value: number
  digits: number
  unit: string
  pct: number
  tone?: 'ok' | 'warn' | 'err'
}

export function SelectedSatellite() {
  const sats = useTelemetryStore((s) => s.sats)
  const selectedId = useTelemetryStore((s) => s.selectedId)
  const sat = sats.find((x) => x.id === selectedId) ?? sats[0]

  const tempPct = Math.min(1, Math.max(0, (sat.temperature_c - 20) / 60))
  const tempTone: Bar['tone'] =
    sat.temperature_c > 70 ? 'err' :
    sat.temperature_c > 50 ? 'warn' : 'ok'

  const bars: Bar[] = [
    { label: 'GPU Util', value: sat.gpu_utilization * 100, digits: 0, unit: '%',    pct: sat.gpu_utilization },
    { label: 'Battery',  value: sat.battery_soc * 100,     digits: 0, unit: '%',    pct: sat.battery_soc },
    { label: 'Temp',     value: sat.temperature_c,         digits: 1, unit: '°C',   pct: tempPct, tone: tempTone },
    { label: 'Downlink', value: sat.downlink_mbps,         digits: 0, unit: 'Mbps', pct: Math.min(1, sat.downlink_mbps / 200) },
  ]

  return (
    <Card selected className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Selected Satellite:{' '}
          <span className="text-accent">{sat.id}</span>
        </div>
        <div className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          {sat.orbit_type} · {sat.gpu_type}
        </div>
      </div>

      <div className="mt-1.5 grid flex-1 min-h-0 grid-cols-[72px_minmax(0,1fr)_220px] gap-4 items-center">
        <div className="flex items-center justify-center">
          <div className="animate-float-y">
            <SatelliteIcon size={64} />
          </div>
        </div>
        <div className="min-h-0">
          <SatParamsGrid />
        </div>
        <div className="flex flex-col gap-1.5">
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
    bar.tone === 'err'  ? '0 0 8px rgba(239,68,68,0.45)' :
    bar.tone === 'warn' ? '0 0 8px rgba(245,158,11,0.45)' :
                          '0 0 8px rgba(59,158,255,0.45)'
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.08em] text-text-lo">{bar.label}</span>
        <span className="flex items-baseline">
          <Num value={bar.value} digits={bar.digits} className="text-[12px] text-text-hi" />
          <span className="ml-1 text-[10px] text-text-lo">{bar.unit}</span>
        </span>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-bg-inset">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${Math.round(bar.pct * 100)}%`, background: fillBg, boxShadow: shadow }}
        />
      </div>
    </div>
  )
}
