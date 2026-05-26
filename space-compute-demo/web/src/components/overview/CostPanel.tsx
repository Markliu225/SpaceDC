import {
  Activity,
  CircleDollarSign,
  Cpu,
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
}

/**
 * CostPanel — 6-tile TCO read-out for the active constellation.
 *
 * Reads cost figures from `src/data/costPresets.ts` (illustrative demo
 * numbers; see the file header for sourcing notes). When the active preset
 * isn't in the table, the entry is synthesised from `totalSats` so the
 * panel always shows numbers.
 *
 * Layout: 3 × 2 grid of <Tile> cells, each = lucide icon + value + unit +
 * label. Matches the density of SystemHealth so the two can sit side-by-side
 * in the bottom row of the new OverviewPage.
 */
export function CostPanel() {
  const activeId  = useTelemetryStore((s) => s.activeConstellationId)
  const totalSats = useTelemetryStore((s) => s.fleet?.total ?? s.constellationDetail?.total_sats ?? 0)
  const cost = getCostPreset(activeId, Math.max(1, totalSats))

  const metrics: CostMetric[] = [
    { icon: CircleDollarSign, label: 'CAPEX',    value: cost.capexUsdM,     digits: 0, unit: '$M' },
    { icon: Activity,         label: 'OPEX/yr',  value: cost.opexUsdMPerYr, digits: 0, unit: '$M' },
    { icon: Cpu,              label: 'Compute',  value: cost.computePflops, digits: 0, unit: 'PFLOPS' },
    { icon: Zap,              label: 'Power',    value: cost.powerKw,       digits: 0, unit: 'kW' },
    { icon: Rocket,           label: 'Payload',  value: cost.launchMassT,   digits: 0, unit: 't' },
    { icon: TrendingUp,       label: 'Payback',  value: cost.paybackYr,     digits: 1, unit: 'yr' },
  ]

  return (
    <Card className="h-full flex flex-col min-h-0">
      <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
        Cost Profile
      </div>
      <div className="mt-2 grid flex-1 grid-cols-3 grid-rows-2 gap-2 min-h-0">
        {metrics.map((m) => <Tile key={m.label} metric={m} />)}
      </div>
    </Card>
  )
}

function Tile({ metric }: { metric: CostMetric }) {
  const Icon = metric.icon
  return (
    <div className="flex items-center gap-2 rounded bg-bg-inset px-2 py-1.5">
      <Icon className="h-4 w-4 text-accent" strokeWidth={1.8} />
      <div className="min-w-0 flex-1">
        <div className="text-[9px] uppercase tracking-[0.10em] text-text-lo">
          {metric.label}
        </div>
        <div className="flex items-baseline">
          <Num
            value={metric.value}
            digits={metric.digits}
            className="text-[14px] leading-tight font-semibold text-text-hi"
          />
          <span className="ml-1 text-[10px] text-text-lo">{metric.unit}</span>
        </div>
      </div>
    </div>
  )
}
