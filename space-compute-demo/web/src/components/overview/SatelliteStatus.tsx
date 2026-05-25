import { useMemo } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Dot, Num } from '../primitives'
import { colors } from '../../design/tokens'

interface Slice { name: string; key: 'online' | 'eclipse' | 'standby' | 'offline'; value: number; color: string }

/**
 * SatelliteStatus — donut + 4-row legend. Built on Recharts.
 *
 * The soft outer glow is faked by a SVG <filter> with a Gaussian blur
 * applied to each <Cell>. Recharts default mount animation is left ON
 * (animate on mount, then static).
 */
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
    <Card>
      <div className="mb-3 text-[11px] uppercase tracking-[0.10em] text-text-md">
        Satellite Status
      </div>

      <div className="grid grid-cols-[160px_1fr] items-center gap-4">
        {/* Donut */}
        <div className="relative h-[160px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <defs>
                <filter id="donutGlow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="3" />
                </filter>
              </defs>
              <Pie
                data={slices}
                dataKey="value"
                innerRadius={56}
                outerRadius={78}
                paddingAngle={2}
                stroke="none"
                animationDuration={900}
              >
                {slices.map((s) => (
                  <Cell
                    key={s.key}
                    fill={s.color}
                    // Glow filter referenced by id; Recharts forwards style onto path.
                    style={{ filter: 'drop-shadow(0 0 6px ' + s.color + '55)' }}
                  />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          {/* Center label, stacked. */}
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <Num
              value={total}
              animate={false}
              className="text-[28px] leading-none font-semibold text-text-hi"
            />
            <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-text-lo">
              Total
            </div>
          </div>
        </div>

        {/* Legend */}
        <div className="flex flex-col gap-2.5">
          {slices.map((s) => {
            const pct = total > 0 ? (s.value / total) * 100 : 0
            return (
              <div key={s.key} className="grid grid-cols-[12px_1fr_auto_auto] items-center gap-2 text-[13px]">
                <Dot color={s.color} size={8} glow={6} />
                <span className="text-text-hi">{s.name}</span>
                <Num value={s.value} animate={false} className="text-text-hi w-6 text-right" />
                <Num value={pct} digits={0} animate={false} className="text-[12px] text-text-lo w-8 text-right" />
              </div>
            )
          })}
        </div>
      </div>
    </Card>
  )
}
