import { Radio, Cpu, Antenna, type LucideIcon } from 'lucide-react'
import { useMissionStore } from '../../store/useMissionStore'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { colors } from '../../design/tokens'
import { Dot } from '../primitives'

function satId(idx: number): string {
  return idx >= 0 ? `SAT-${String(idx + 1).padStart(2, '0')}` : '—'
}

interface CastRow {
  role: string
  icon: LucideIcon
  value: string
  /** Fleet index to select on click (ground station has none). */
  selectIdx?: number
  tint: string
}

/**
 * MissionCast — the three players in the choreography. Clicking the Sensor
 * or Hub row sets selectedSatIdx (shared store) so the corresponding sat
 * is highlighted in the 3D scene + other panels.
 */
export function MissionCast() {
  const mission     = useMissionStore((s) => s.mission)
  const setSelected = useTelemetryStore((s) => s.setSelectedSatIdx)
  const selectedIdx = useTelemetryStore((s) => s.selectedSatIdx)

  const rows: CastRow[] = [
    { role: 'Sensor',  icon: Radio,   value: satId(mission.sensor_idx), selectIdx: mission.sensor_idx, tint: colors.accent },
    { role: 'Compute Hub', icon: Cpu, value: satId(mission.hub_idx),    selectIdx: mission.hub_idx,    tint: '#A78BFA' },
    { role: 'Ground',  icon: Antenna, value: mission.ground_id || '—',  tint: colors.ok },
  ]

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-[0.10em] text-text-lo">Cast</span>
      {rows.map((r) => {
        const Icon = r.icon
        const selected = r.selectIdx !== undefined && r.selectIdx >= 0 && r.selectIdx === selectedIdx
        const clickable = r.selectIdx !== undefined && r.selectIdx >= 0
        return (
          <button
            key={r.role}
            type="button"
            disabled={!clickable}
            onClick={() => clickable && setSelected(r.selectIdx!)}
            className={[
              'grid grid-cols-[16px_1fr_auto] items-center gap-2 rounded px-2 py-1 text-left text-[12px] transition-colors',
              selected ? 'bg-accent/15 ring-1 ring-accent/40' :
              clickable ? 'hover:bg-bg-cardHi' : '',
            ].join(' ')}
          >
            <Icon size={13} strokeWidth={1.8} style={{ color: r.tint }} />
            <span className="text-text-md">{r.role}</span>
            <span className="flex items-center gap-1.5">
              <Dot color={r.tint} size={6} glow={4} />
              <span className="tabular text-text-hi">{r.value}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}
