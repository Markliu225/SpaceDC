import { useMemo } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Dot, Num } from '../primitives'
import { colors } from '../../design/tokens'

interface Slice { name: string; key: 'online' | 'eclipse' | 'standby' | 'offline'; value: number; color: string }

export function SatelliteStatus() {
  const sats = useTelemetryStore((s) => s.sats)

  const slices: Slice[] = useMemo(() => {
    const c: Record<Slice['key'], number> = { online: 0, eclipse: 0, standby: 0, offline: 0 }
    for (const s of sats) c[s.status]++
    return [
      { name: 'Online',  key: 'online',  value: c.online,  color: colors.status.online  },
      { name: 'Eclipse', key: 'eclipse', value: c.eclipse, color: colors.status.eclipse },
      { name: 'Standby', key: 'standby', value: c.standby, color: colors.status.standby },
      { name: 'Offline', key: 'offline', value: c.offline, color: colors.status.offline },
    ]
  }, [sats])

  const total = sats.length

  return (
    <Card className="h-full flex flex-col min-h-0">
      <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
        Satellite Status
      </div>

      <div className="mt-1 grid flex-1 min-h-0 grid-cols-[110px_1fr] items-center gap-3">
        <div className="relative h-full min-h-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={slices}
                dataKey="value"
                innerRadius="60%"
                outerRadius="86%"
                paddingAngle={2}
                stroke="none"
                animationDuration={800}
              >
                {slices.map((s) => (
                  <Cell
                    key={s.key}
                    fill={s.color}
                    style={{ filter: `drop-shadow(0 0 6px ${s.color}55)` }}
                  />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <Num
              value={total}
              animate={false}
              className="text-[22px] leading-none font-semibold text-text-hi"
            />
            <div className="mt-0.5 text-[9px] uppercase tracking-[0.14em] text-text-lo">
              Total
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          {slices.map((s) => {
            const pct = total > 0 ? (s.value / total) * 100 : 0
            return (
              <div key={s.key} className="grid grid-cols-[10px_1fr_auto_auto] items-center gap-2 text-[12px]">
                <Dot color={s.color} size={7} glow={5} />
                <span className="text-text-hi">{s.name}</span>
                <Num value={s.value} animate={false} className="text-text-hi w-5 text-right" />
                <Num value={pct} digits={0} animate={false} className="text-[11px] text-text-lo w-7 text-right" />
              </div>
            )
          })}
        </div>
      </div>
    </Card>
  )
}
