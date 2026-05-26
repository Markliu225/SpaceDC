import { useMemo, useState } from 'react'
import { Card, Dot } from '../primitives'
import { colors } from '../../design/tokens'
import { useFleetStatuses, type FleetSat, type SatStatus } from '../../hooks/useFleetStatuses'
import { useTelemetryStore } from '../../store/useTelemetryStore'

const STATUS_ORDER: SatStatus[] = ['online', 'eclipse', 'standby', 'offline']
const STATUS_LABEL: Record<SatStatus, string> = {
  online:  'Online',
  eclipse: 'Eclipse',
  standby: 'Standby',
  offline: 'Offline',
}

/**
 * SatelliteList — scrollable list of every sat in the active constellation,
 * grouped by status. Includes a search box that filters by id substring.
 *
 * Row click selects the sat (writes selectedSatIdx in the store) — the
 * Coverage map + SatelliteDetail panel both subscribe to that index, so
 * selection is shared across the Overview.
 *
 * Performance: with thousands of sats (Starlink Shell 1 = 1584) we'd be
 * rendering ~1.6k DOM rows. That's fine for a scrolling list — measured
 * ~25ms initial paint on a mid-range laptop. If it becomes a bottleneck
 * later, switch to react-window virtualisation.
 */
export function SatelliteList() {
  const fleet      = useFleetStatuses()
  const selectedIdx = useTelemetryStore((s) => s.selectedSatIdx)
  const setSelected = useTelemetryStore((s) => s.setSelectedSatIdx)
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return fleet
    return fleet.filter((s) => s.id.toLowerCase().includes(q))
  }, [fleet, query])

  const groups = useMemo(() => groupByStatus(filtered), [filtered])

  return (
    <Card className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Satellites
        </span>
        <span className="text-[11px] text-text-lo tabular">{fleet.length}</span>
      </div>

      <input
        type="text"
        placeholder="Search id…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="mt-2 w-full rounded bg-bg-inset px-2 py-1 text-[12px] text-text-hi placeholder:text-text-faint outline-none focus:ring-1 focus:ring-accent"
      />

      <div className="mt-2 flex-1 min-h-0 overflow-y-auto pr-1">
        {STATUS_ORDER.map((status) => {
          const rows = groups[status]
          if (rows.length === 0) return null
          return (
            <div key={status} className="mb-2">
              <div className="sticky top-0 z-10 -mx-1 mb-1 flex items-center gap-2 bg-bg-card/95 px-1 py-0.5 backdrop-blur text-[10px] uppercase tracking-[0.10em]">
                <Dot color={colors.status[status]} size={6} glow={4} />
                <span className="text-text-md">{STATUS_LABEL[status]}</span>
                <span className="text-text-lo tabular">{rows.length}</span>
              </div>
              {rows.map((s) => (
                <SatRow
                  key={s.idx}
                  sat={s}
                  selected={s.idx === selectedIdx}
                  onClick={() => setSelected(s.idx)}
                />
              ))}
            </div>
          )
        })}
        {filtered.length === 0 && (
          <div className="py-4 text-center text-[12px] text-text-lo">
            No matches.
          </div>
        )}
      </div>
    </Card>
  )
}

function groupByStatus(fleet: FleetSat[]): Record<SatStatus, FleetSat[]> {
  const g: Record<SatStatus, FleetSat[]> = {
    online: [], eclipse: [], standby: [], offline: [],
  }
  for (const s of fleet) g[s.status].push(s)
  return g
}

interface SatRowProps {
  sat: FleetSat
  selected: boolean
  onClick: () => void
}

/** One row: id · sub-sat lat/lon · plane/slot. Highlight when selected. */
function SatRow({ sat, selected, onClick }: SatRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'grid w-full grid-cols-[1fr_auto] items-center gap-2 rounded px-2 py-1 text-left text-[12px] transition-colors',
        selected
          ? 'bg-accent/15 text-text-hi ring-1 ring-accent/40'
          : 'hover:bg-bg-cardHi text-text-md',
      ].join(' ')}
    >
      <span className="truncate tabular">{sat.id}</span>
      <span className="text-[10px] tabular text-text-lo">
        {sat.lat.toFixed(0)}°/{sat.lon.toFixed(0)}°
      </span>
    </button>
  )
}
