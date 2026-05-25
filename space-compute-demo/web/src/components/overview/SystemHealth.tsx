import { RadioTower, Rocket, Thermometer, Zap } from 'lucide-react'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card } from '../primitives'
import type { LucideIcon } from 'lucide-react'

interface Row {
  key: string
  name: string
  icon: LucideIcon
  status: 'nominal' | 'warn' | 'fault'
}

/**
 * SystemHealth — 4 rows: Power / Thermal / Propulsion / Comms.
 * Per design brief:
 *   - icon container 28x28, cyan tint, rounded 6px
 *   - lucide icons stroke 1.5, 16px
 *   - status pill 11px uppercase + tracking
 *   - row separator 1px border.weak, full-width
 *   - hover row: bg-card-hi
 */
export function SystemHealth() {
  const h = useTelemetryStore((s) => s.health)
  const rows: Row[] = [
    { key: 'power',      name: 'Power',      icon: Zap,        status: h.power },
    { key: 'thermal',    name: 'Thermal',    icon: Thermometer, status: h.thermal },
    { key: 'propulsion', name: 'Propulsion', icon: Rocket,     status: h.propulsion },
    { key: 'comms',      name: 'Comms',      icon: RadioTower, status: h.comms },
  ]
  return (
    <Card>
      <div className="mb-2 text-[11px] uppercase tracking-[0.10em] text-text-md">
        System Health
      </div>
      <div className="-mx-2">
        {rows.map((r, i) => (
          <HealthRow
            key={r.key}
            row={r}
            isLast={i === rows.length - 1}
          />
        ))}
      </div>
    </Card>
  )
}

function HealthRow({ row, isLast }: { row: Row; isLast: boolean }) {
  const Icon = row.icon
  const tone = STATUS_TONE[row.status]
  return (
    <div className={`group flex items-center gap-3 px-2 py-2.5 transition-colors duration-150 hover:bg-bg-card-hi ${isLast ? '' : 'border-b border-border-weak'}`}>
      <span
        aria-hidden="true"
        className="grid place-items-center rounded-md"
        style={{
          width: 28,
          height: 28,
          background: 'rgba(59,158,255,0.08)',
        }}
      >
        <Icon size={16} strokeWidth={1.5} className="text-accent" />
      </span>
      <span className="text-[13px] text-text-hi">{row.name}</span>
      <span className="flex-1" />
      <span
        className={`rounded px-1.5 py-0.5 text-[11px] uppercase tracking-[0.12em] ${tone.text}`}
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
  nominal: 'Nominal',
  warn:    'Warning',
  fault:   'Fault',
} as const
