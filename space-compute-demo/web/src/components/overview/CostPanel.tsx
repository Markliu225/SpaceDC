import {
  Activity,
  CircleDollarSign,
  Clock,
  Cpu,
  Package,
  Rocket,
  TrendingUp,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { Card, Num } from '../primitives'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { getCostPreset } from '../../data/costPresets'

interface CostMetric {
  icon: LucideIcon
  label: string
  value: number
  digits: number
  unit: string
  /** Optional sub-line ("$M / sat", "5 yr design", etc.). */
  sub?: string
}

/**
 * CostPanel — TCO read-out for the active constellation.
 *
 * 4 × 2 = 8 tiles. Numbers come from `src/data/costPresets.ts` — see the
 * file header for sourcing notes. Each tile = lucide icon + value + unit +
 * optional sub-line. Header strip shows total fleet + sat lifetime so the
 * eight body tiles can focus on pure economics.
 *
 * When the active preset isn't in the table the entry is synthesised from
 * `totalSats` so the panel never blanks out.
 */
export function CostPanel() {
  const activeId    = useTelemetryStore((s) => s.activeConstellationId)
  const totalSats   = useTelemetryStore((s) =>
    s.fleet?.total ?? s.constellationDetail?.total_sats ?? 0)
  const constName   = useTelemetryStore((s) =>
    s.constellationDetail?.name ?? s.fleet?.name ?? '—')
  const cost = getCostPreset(activeId, Math.max(1, totalSats))

  // Derived headline figures.
  const lifetimeUsdM   = cost.capexUsdM + cost.opexUsdMPerYr * cost.satLifetimeYr
  const usdPerPflopK   = cost.computePflops > 0
    ? (cost.capexUsdM * 1000) / cost.computePflops
    : 0

  const metrics: CostMetric[] = [
    { icon: CircleDollarSign, label: 'Capital Expenditure',  value: cost.capexUsdM,        digits: 0, unit: 'million USD',
      sub: `${cost.capexPerSatUsdM.toFixed(1)} million per satellite` },
    { icon: Activity,         label: 'Operating Expense',    value: cost.opexUsdMPerYr,    digits: 0, unit: 'million USD / year' },
    { icon: Rocket,           label: 'Launch Cost',          value: cost.launchUsdM,       digits: 0, unit: 'million USD',
      sub: `${cost.launchMassT.toFixed(0)} tonnes payload` },
    { icon: TrendingUp,       label: 'Lifetime Total',       value: lifetimeUsdM,          digits: 0, unit: 'million USD',
      sub: `${cost.satLifetimeYr} year design life` },
    { icon: Cpu,              label: 'Compute Capacity',     value: cost.computePflops,    digits: 0, unit: 'petaFLOPS',
      sub: `${usdPerPflopK.toFixed(1)} thousand USD per petaFLOP` },
    { icon: Zap,              label: 'Power Draw',           value: cost.powerKw,          digits: 0, unit: 'kilowatts' },
    { icon: Package,          label: 'Cost Per Satellite',   value: cost.capexPerSatUsdM,  digits: 1, unit: 'million USD' },
    { icon: Clock,            label: 'Payback Period',       value: cost.paybackYr,        digits: 1, unit: 'years' },
  ]

  return (
    <Card dense className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Cost Profile
        </span>
        <span className="text-[10px] tabular text-text-lo truncate">
          {constName} · {totalSats} satellites
        </span>
      </div>
      <div className="mt-2 grid flex-1 grid-cols-4 grid-rows-2 gap-1.5 min-h-0">
        {metrics.map((m) => <Tile key={m.label} metric={m} />)}
      </div>
    </Card>
  )
}

function Tile({ metric }: { metric: CostMetric }) {
  const Icon = metric.icon
  return (
    <div className="flex min-w-0 items-center gap-1.5 rounded bg-bg-inset px-2 py-1">
      <Icon className="h-4 w-4 shrink-0 text-accent" strokeWidth={1.8} />
      <div className="min-w-0 flex-1">
        <div className="text-[9px] uppercase tracking-[0.10em] text-text-lo">
          {metric.label}
        </div>
        <div className="flex items-baseline">
          <Num
            value={metric.value}
            digits={metric.digits}
            className="text-[13px] leading-tight font-semibold text-text-hi"
          />
          <span className="ml-1 text-[10px] text-text-lo">{metric.unit}</span>
        </div>
        {metric.sub && (
          <div className="truncate text-[9px] text-text-faint tabular">{metric.sub}</div>
        )}
      </div>
    </div>
  )
}
