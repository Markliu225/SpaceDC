import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Num } from '../primitives'
import { AreaChart, Area, ResponsiveContainer } from 'recharts'
import { useId } from 'react'

/**
 * LinkAndTraffic — compact stacked sparklines, sized to fit the cell.
 */
export function LinkAndTraffic() {
  const dl = useTelemetryStore((s) => s.downlink_history)
  const ul = useTelemetryStore((s) => s.uplink_history)

  return (
    <Card className="h-full flex flex-col min-h-0">
      <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
        Link &amp; Traffic
      </div>
      <div className="mt-1 flex-1 min-h-0 grid grid-rows-2 gap-1.5">
        <MiniSpark title="Downlink" data={dl} color="#3B9EFF" />
        <MiniSpark title="Uplink"   data={ul} color="#22D3EE" />
      </div>
    </Card>
  )
}

function MiniSpark({ title, data, color }: { title: string; data: number[]; color: string }) {
  const gid = useId().replace(/:/g, '')
  const gradId = `mini-grad-${gid}`
  const current = data[data.length - 1] ?? 0
  const chartData = data.map((v, i) => ({ i, v }))
  return (
    <div className="min-h-0 flex flex-col">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-lo">{title}</span>
        <span className="flex items-baseline">
          <Num value={current} digits={0} animate={false} className="text-[14px] text-text-hi" />
          <span className="ml-1 text-[10px] text-text-lo">Mbps</span>
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%"   stopColor={color} stopOpacity={0.55} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="v"
              stroke={color}
              strokeWidth={1.4}
              fill={`url(#${gradId})`}
              dot={false}
              isAnimationActive={false}
              style={{ filter: `drop-shadow(0 0 4px ${color}66)` }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
