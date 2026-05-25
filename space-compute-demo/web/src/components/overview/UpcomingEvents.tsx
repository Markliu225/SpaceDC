import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card } from '../primitives'

function fmtCountdown(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}h${m % 60}m`
  }
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

/**
 * UpcomingEvents — 3 rows, designed for ~144 height in a narrow column.
 * Truncates the sub-text to keep the row tidy in 200px-wide tiles.
 */
export function UpcomingEvents() {
  const items = useTelemetryStore((s) => s.upcoming)
  return (
    <Card className="h-full flex flex-col min-h-0 overflow-hidden">
      <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
        Upcoming
      </div>
      <div className="-mx-1 mt-1 flex flex-col flex-1 min-h-0 justify-between">
        {items.map((e, i) => (
          <div
            key={e.id}
            className={`px-1 py-0.5 cursor-pointer hover:bg-bg-card-hi ${i === items.length - 1 ? '' : 'border-b border-border-weak'}`}
          >
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] tabular font-mono text-text-md">{e.ts}</span>
              <span
                className={`text-[11px] tabular font-mono text-text-hi ${e.countdown_s < 60 ? 'animate-live-pulse' : ''}`}
              >
                T-{fmtCountdown(e.countdown_s)}
              </span>
            </div>
            <div className="text-[11px] text-text-hi truncate">{e.label}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}
