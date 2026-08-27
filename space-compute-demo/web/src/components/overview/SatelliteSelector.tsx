import { ChevronDown } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useFleetStatuses, type FleetSat, type SatStatus } from '../../hooks/useFleetStatuses'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { colors } from '../../design/tokens'
import { Dot } from '../primitives'

const STATUS_ORDER: SatStatus[] = ['online', 'eclipse', 'standby', 'offline']
const STATUS_LABEL: Record<SatStatus, string> = {
  online:  'Online',
  eclipse: 'Eclipse',
  standby: 'Standby',
  offline: 'Offline',
}

/**
 * SatelliteSelector — compact dropdown picker (button + popover listbox)
 * that replaces the standalone SatelliteList panel. Designed to slot into
 * the SatelliteDetail header.
 *
 * Popover contents: search box + status-grouped list, same data shape as
 * the old SatelliteList. The popover is absolutely positioned within the
 * trigger's wrapper so the parent panel can stay `overflow-hidden` and
 * still let the popover overflow below.
 */
export function SatelliteSelector() {
  const fleet       = useFleetStatuses()
  const selectedIdx = useTelemetryStore((s) => s.selectedSatIdx)
  const setSelected = useTelemetryStore((s) => s.setSelectedSatIdx)

  const [open, setOpen]   = useState(false)
  const [query, setQuery] = useState('')
  const containerRef      = useRef<HTMLDivElement>(null)

  // Click-outside close — same pattern as ConstellationSelector.
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return fleet
    return fleet.filter((s) => s.id.toLowerCase().includes(q))
  }, [fleet, query])

  const groups = useMemo(() => groupByStatus(filtered), [filtered])
  const selected = fleet[selectedIdx]

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded border border-border-weak bg-bg-inset/60 px-2 py-0.5 text-[12px] text-text-hi hover:border-border-med"
      >
        <span className="tabular">{selected?.id ?? '—'}</span>
        {selected && (
          <Dot color={colors.status[selected.status]} size={6} />
        )}
        <ChevronDown size={12} strokeWidth={1.5} className="text-text-md" />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute right-0 top-full z-30 mt-1 w-[240px] rounded border border-border-med bg-bg-card shadow-card"
        >
          <div className="border-b border-border-weak p-2">
            <input
              type="text"
              placeholder="Search id…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
              className="w-full rounded bg-bg-inset px-2 py-1 text-[12px] text-text-hi placeholder:text-text-faint outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <div className="max-h-72 overflow-y-auto p-1">
            {STATUS_ORDER.map((status) => {
              const rows = groups[status]
              if (rows.length === 0) return null
              return (
                <div key={status} className="mb-1">
                  <div className="sticky top-0 z-10 -mx-1 mb-0.5 flex items-center gap-2 bg-bg-card/95 px-2 py-0.5 backdrop-blur text-[10px] uppercase tracking-[0.10em]">
                    <Dot color={colors.status[status]} size={5} />
                    <span className="text-text-md">{STATUS_LABEL[status]}</span>
                    <span className="text-text-lo tabular">{rows.length}</span>
                  </div>
                  {rows.map((s) => (
                    <Row
                      key={s.idx}
                      sat={s}
                      selected={s.idx === selectedIdx}
                      onClick={() => {
                        setSelected(s.idx)
                        setOpen(false)
                      }}
                    />
                  ))}
                </div>
              )
            })}
            {filtered.length === 0 && (
              <div className="py-3 text-center text-[12px] text-text-lo">No matches.</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function groupByStatus(fleet: FleetSat[]): Record<SatStatus, FleetSat[]> {
  const g: Record<SatStatus, FleetSat[]> = {
    online: [], eclipse: [], standby: [], offline: [],
  }
  for (const s of fleet) g[s.status].push(s)
  return g
}

interface RowProps {
  sat: FleetSat
  selected: boolean
  onClick: () => void
}

function Row({ sat, selected, onClick }: RowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'grid w-full grid-cols-[1fr_auto] items-center gap-2 rounded px-2 py-1 text-left text-[12px] transition-colors',
        selected
          ? 'bg-accent/15 text-text-hi ring-1 ring-accent/40'
          : 'hover:bg-bg-card-hi text-text-md',
      ].join(' ')}
    >
      <span className="truncate tabular">{sat.id}</span>
      <span className="text-[10px] tabular text-text-lo">
        {sat.lat.toFixed(0)}°/{sat.lon.toFixed(0)}°
      </span>
    </button>
  )
}
