import { RadioTower, Rocket, Thermometer, Zap } from 'lucide-react'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card } from '../primitives'
import type { LucideIcon } from 'lucide-react'

interface Row { key: string; name: string; icon: LucideIcon; status: 'nominal' | 'warn' | 'fault' }

export function SystemHealth() {
  const h = useTelemetryStore((s) => s.health)
  const rows: Row[] = [
    { key: 'power',      name: 'Power',      icon: Zap,        status: h.power },
    { key: 'thermal',    name: 'Thermal',    icon: Thermometer, status: h.thermal },
    { key: 'propulsion', name: 'Propulsion', icon: Rocket,     status: h.propulsion },
    { key: 'comms',      name: 'Comms',      icon: RadioTower, status: h.comms },
  ]
  return (
    <Card className="h-full flex flex-col min-h-0 overflow-hidden">
      <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
        System Health
      </div>
      <div className="-mx-1.5 mt-1 flex flex-col flex-1 min-h-0 justify-between">
        {rows.map((r, i) => (
          <HealthRow key={r.key} row={r} isLast={i === rows.length - 1} />
        ))}
      </div>
    </Card>
  )
}

function HealthRow({ row, isLast }: { row: Row; isLast: boolean }) {
  const Icon = row.icon
  const tone = STATUS_TONE[row.status]
  return (
    <div className={`flex items-center gap-2 px-1.5 py-0.5 transition-colors duration-150 hover:bg-bg-card-hi ${isLast ? '' : 'border-b border-border-weak'}`}>
      <span
        aria-hidden="true"
        className="grid place-items-center rounded-md"
        style={{ width: 20, height: 20, background: 'rgba(59,158,255,0.10)' }}
      >
        <Icon size={12} strokeWidth={1.5} className="text-accent" />
      </span>
      <span className="text-[11px] text-text-hi">{row.name}</span>
      <span className="flex-1" />
      <span
        className={`rounded px-1.5 py-px text-[9px] uppercase tracking-[0.10em] ${tone.text}`}
        style={{ background: tone.bg }}
      >
        {STATUS_LABEL[row.status]}
      </span>
    </div>
  )
}

const STATUS_TONE = {
  nominal: { text: 'text-ok',   bg: 'rgba(34,197,94,0.10)' },
  warn:    { text: 'text-warn', bg: 'rgba(245,158,11,0.10)' },
  fault:   { text: 'text-err',  bg: 'rgba(239,68,68,0.12)' },
} as const

const STATUS_LABEL = {
  nominal: 'OK',
  warn:    'WARN',
  fault:   'FAULT',
} as const
