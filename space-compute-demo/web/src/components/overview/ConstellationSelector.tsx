import { ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { switchConstellation } from '../../hooks/useBackendBridge'
import { Card, Num } from '../primitives'

/**
 * ConstellationSelector — the single point of truth for which constellation
 * the demo is showing. Lives in the top row alongside the KPI tiles; takes
 * its options from useTelemetryStore.presets (filled by useBackendBridge
 * from GET /constellations).
 *
 * On change: POST /constellation/{id}, then the next 1Hz WS state_update
 * carries the new fleet snapshot which the bridge mirrors into the store —
 * NetworkOverview / SatelliteStatus react automatically.
 */
export function ConstellationSelector() {
  const presets = useTelemetryStore((s) => s.presets)
  const activeId = useTelemetryStore((s) => s.activeConstellationId)
  const fleet = useTelemetryStore((s) => s.fleet)

  const active = presets.find((p) => p.id === activeId)
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Click-outside close.
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <Card dense className="flex flex-col justify-center min-h-0">
      <div className="text-[10px] uppercase tracking-[0.10em] text-text-md">
        Constellation
      </div>
      <div ref={containerRef} className="relative mt-1">
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center justify-between gap-2 rounded border border-border-weak px-2 py-1 text-[13px] text-text-hi hover:border-border-med"
        >
          <span className="truncate">{active?.name ?? activeId}</span>
          <ChevronDown size={14} strokeWidth={1.5} className="shrink-0 text-text-md" />
        </button>
        {open && (
          <ul
            role="listbox"
            className="absolute right-0 left-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded border border-border-med bg-bg-card shadow-card"
          >
            {presets.length === 0 && (
              <li className="px-3 py-2 text-[12px] italic text-text-lo">
                backend offline — no presets
              </li>
            )}
            {presets.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => { setOpen(false); void switchConstellation(p.id) }}
                  className={`block w-full px-3 py-1.5 text-left text-[12px] hover:bg-bg-card-hi ${p.id === activeId ? 'text-accent' : 'text-text-md'}`}
                >
                  <div className="truncate">{p.name}</div>
                  <div className="text-[10px] text-text-lo tabular">
                    {p.planes}p × {p.sats_per_plane}s = {p.total_sats} · {p.inclination_deg.toFixed(1)}° · {p.altitude_km.toFixed(0)} km
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="mt-1.5 text-[11px] text-text-lo tabular">
        {fleet
          ? <>{fleet.planes}p · {fleet.sats_per_plane}s · {fleet.inclination_deg.toFixed(1)}°</>
          : <>—</>}
        {' '}
        <span className="ml-1">
          <Num value={fleet?.altitude_km ?? 0} digits={0} className="text-text-md" /> km
        </span>
      </div>
    </Card>
  )
}
