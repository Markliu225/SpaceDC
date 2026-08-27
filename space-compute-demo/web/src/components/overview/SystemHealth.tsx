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
        className="grid h-5 w-5 place-items-center rounded"
      >
        <Icon size={12} strokeWidth={1.5} className="text-text-md" />
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

// Tinted fills = the ok / warn / err tokens at low alpha (see design/tokens).
const STATUS_TONE = {
  nominal: { text: 'text-ok',   bg: 'rgba(63,184,113,0.12)' },
  warn:    { text: 'text-warn', bg: 'rgba(224,168,58,0.12)' },
  fault:   { text: 'text-err',  bg: 'rgba(224,86,79,0.12)' },
} as const

const STATUS_LABEL = {
  nominal: 'OK',
  warn:    'WARN',
  fault:   'FAULT',
} as const
