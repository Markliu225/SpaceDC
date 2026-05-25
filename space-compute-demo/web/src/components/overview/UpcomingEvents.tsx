import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card } from '../primitives'

function fmtCountdown(s: number): string {
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}h ${m % 60}m`
  }
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

/**
 * UpcomingEvents — 3 rows. Countdown pulses when < 60s.
 */
export function UpcomingEvents() {
  const items = useTelemetryStore((s) => s.upcoming)
  return (
    <Card>
      <div className="mb-2 text-[11px] uppercase tracking-[0.10em] text-text-md">
        Upcoming Events
      </div>
      <div className="-mx-2">
        {items.map((e, i) => (
          <div
            key={e.id}
            className={`grid grid-cols-[80px_1fr_auto] items-center gap-3 px-2 py-3 cursor-pointer hover:bg-bg-card-hi ${i === items.length - 1 ? '' : 'border-b border-border-weak'}`}
          >
            <span className="text-[12px] tabular font-mono text-text-md">{e.ts}</span>
            <div className="min-w-0">
              <div className="text-[13px] text-text-hi truncate">{e.label}</div>
              <div className="text-[12px] text-text-lo truncate">{e.sub}</div>
            </div>
            <span
              className={`text-[13px] tabular font-mono text-text-hi whitespace-nowrap ${e.countdown_s < 60 ? 'animate-live-pulse' : ''}`}
            >
              T-{fmtCountdown(e.countdown_s)}
            </span>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="mt-2 w-full text-left text-[12px] text-accent hover:underline"
      >
        View all schedule ›
      </button>
    </Card>
  )
}
