import { useMemo } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Dot, Num } from '../primitives'
import { colors } from '../../design/tokens'

interface Slice { name: string; key: 'online' | 'eclipse' | 'standby' | 'offline'; value: number; color: string }

/**
 * SatelliteStatus — donut + 4-row legend, fed directly from
 * useTelemetryStore.fleet (which mirrors backend's /state.constellation).
 * Falls back to legacy `sats[]` counting so the panel still renders if the
 * backend hasn't pushed a snapshot yet (initial reload, backend offline).
 */
export function SatelliteStatus() {
  const fleet = useTelemetryStore((s) => s.fleet)
  const sats  = useTelemetryStore((s) => s.sats)

  const slices: Slice[] = useMemo(() => {
    let counts: Record<Slice['key'], number>
    if (fleet) {
      counts = {
        online:  fleet.online,
        eclipse: fleet.eclipse,
        standby: fleet.standby,
        offline: fleet.offline,
      }
    } else {
      counts = { online: 0, eclipse: 0, standby: 0, offline: 0 }
      for (const s of sats) counts[s.status]++
    }
    return [
      { name: 'Online',  key: 'online',  value: counts.online,  color: colors.status.online  },
      { name: 'Eclipse', key: 'eclipse', value: counts.eclipse, color: colors.status.eclipse },
      { name: 'Standby', key: 'standby', value: counts.standby, color: colors.status.standby },
      { name: 'Offline', key: 'offline', value: counts.offline, color: colors.status.offline },
    ]
  }, [fleet, sats])

  const total = slices.reduce((a, s) => a + s.value, 0)

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
                <Dot color={s.color} size={7} />
                <span className="text-text-hi">{s.name}</span>
                <Num value={s.value} animate={false} className="text-text-hi w-10 text-right" />
                <Num value={pct} digits={0} animate={false} className="text-[11px] text-text-lo w-7 text-right" />
              </div>
            )
          })}
        </div>
      </div>
    </Card>
  )
}
