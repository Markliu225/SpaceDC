import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Dot } from '../primitives'
import { colors } from '../../design/tokens'
import type { EventEntry } from '../../store/useTelemetryStore'

const KIND_COLOR: Record<EventEntry['kind'], string> = {
  ok:   colors.ok,
  info: colors.accent,
  warn: colors.warn,
  err:  colors.err,
}

/**
 * EventLog — scrollable list inside a fixed-height card. With 144 height
 * the visible window is ~4 rows; older events scroll within the panel
 * (acceptable since the rest of the page never scrolls).
 */
export function EventLog() {
  const all = useTelemetryStore((s) => s.events)
  const [filter, setFilter] = useState<EventEntry['kind'] | 'all'>('all')
  const [open, setOpen] = useState(false)

  const events = filter === 'all' ? all : all.filter((e) => e.kind === filter)

  return (
    <Card className="h-full flex flex-col min-h-0 overflow-hidden">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Event Log
        </span>
        <FilterDropdown
          value={filter}
          open={open}
          onOpen={setOpen}
          onChange={(v) => { setFilter(v); setOpen(false) }}
        />
      </div>

      <div className="-mx-2 mt-1 flex-1 min-h-0 overflow-y-auto">
        {events.length === 0 ? (
          <div className="px-2 py-3 text-[12px] italic text-text-lo">— no events —</div>
        ) : events.map((e) => (
          <div
            key={e.id}
            className="animate-event-fade-in grid grid-cols-[58px_12px_minmax(0,1fr)_auto] items-center gap-2 px-2 h-6 hover:bg-bg-card-hi"
          >
            <span className="text-[10px] tabular font-mono text-text-md">{e.ts}</span>
            <Dot color={KIND_COLOR[e.kind]} size={6} glow={4} />
            <span className="text-[11px] text-text-hi truncate">{e.label}</span>
            <span className="text-[10px] tabular text-text-lo whitespace-nowrap">{e.entities}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

const FILTER_OPTIONS: { value: EventEntry['kind'] | 'all'; label: string }[] = [
  { value: 'all',  label: 'All Events'  },
  { value: 'ok',   label: 'Status OK'   },
  { value: 'info', label: 'Info'        },
  { value: 'warn', label: 'Warnings'    },
  { value: 'err',  label: 'Errors'      },
]

function FilterDropdown({
  value, open, onOpen, onChange,
}: {
  value: EventEntry['kind'] | 'all'
  open: boolean
  onOpen: (v: boolean) => void
  onChange: (v: EventEntry['kind'] | 'all') => void
}) {
  const label = FILTER_OPTIONS.find((o) => o.value === value)?.label ?? 'All Events'
  return (
    <div className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => onOpen(!open)}
        className="flex items-center gap-1 rounded border border-border-weak px-1.5 py-px text-[10px] text-text-md hover:border-border-med hover:text-text-hi"
      >
        {label}
        <ChevronDown size={11} strokeWidth={1.5} />
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute right-0 top-full z-10 mt-1 w-32 overflow-hidden rounded border border-border-med bg-card shadow-card"
        >
          {FILTER_OPTIONS.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                onClick={() => onChange(o.value)}
                className={`block w-full px-3 py-1 text-left text-[11px] hover:bg-bg-card-hi ${o.value === value ? 'text-accent' : 'text-text-md'}`}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
