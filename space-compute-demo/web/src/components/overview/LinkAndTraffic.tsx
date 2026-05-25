import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Sparkline } from '../primitives'

/**
 * LinkAndTraffic — two stacked Downlink / Uplink sparklines inside one
 * card. A border.weak divider sits between them.
 */
export function LinkAndTraffic() {
  const dl = useTelemetryStore((s) => s.downlink_history)
  const ul = useTelemetryStore((s) => s.uplink_history)

  const dlCurrent = dl[dl.length - 1] ?? 0
  const ulCurrent = ul[ul.length - 1] ?? 0

  // 3 evenly spaced HH:MM tick labels, anchored to wall clock so they
  // drift naturally rather than being fixed strings.
  const ts = makeTimestamps()

  return (
    <Card>
      <div className="mb-3 text-[11px] uppercase tracking-[0.10em] text-text-md">
        Link &amp; Traffic
      </div>
      <Sparkline
        title="Downlink Throughput"
        data={dl}
        current={dlCurrent}
        unit="Mbps"
        digits={0}
        color="#3B9EFF"
        timestamps={ts}
      />
      <div className="my-4 h-px bg-border-weak" />
      <Sparkline
        title="Uplink Throughput"
        data={ul}
        current={ulCurrent}
        unit="Mbps"
        digits={0}
        color="#22D3EE"
        timestamps={ts}
      />
    </Card>
  )
}

function makeTimestamps(): string[] {
  const now = new Date()
  const fmt = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const minus = (mins: number) => new Date(now.getTime() - mins * 60_000)
  return [fmt(minus(60)), fmt(minus(30)), fmt(now)]
}
