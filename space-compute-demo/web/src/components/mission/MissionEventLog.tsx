import { useEffect, useRef, useState } from 'react'
import { useMissionStore } from '../../store/useMissionStore'
import { Card, Dot } from '../primitives'
import { colors } from '../../design/tokens'
import type { MissionPhase } from '../../types/messages'

interface LogEntry {
  id: number
  ts: string
  kind: 'info' | 'ok' | 'accent'
  text: string
}

/** Human log line emitted when each phase begins. */
const PHASE_LOG: Record<Exclude<MissionPhase, 'idle'>, { kind: LogEntry['kind']; text: string }> = {
  acquire:  { kind: 'info',   text: 'AOI acquired — Pacific NW maritime sector' },
  capture:  { kind: 'accent', text: 'Sensor capture — 5.0 GB raw imagery' },
  route:    { kind: 'accent', text: 'ISL routing payload to compute hub' },
  compute:  { kind: 'accent', text: 'On-orbit inference — ship detection running' },
  downlink: { kind: 'ok',     text: 'Downlinking 2 MB result via ground link' },
  deliver:  { kind: 'ok',     text: 'Result delivered — 7 vessels detected' },
}

function hhmmss(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const KIND_COLOR: Record<LogEntry['kind'], string> = {
  info:   colors.text.lo,
  ok:     colors.ok,
  accent: colors.accent,
}

/**
 * MissionEventLog — appends a line each time the mission enters a new
 * phase, newest on top. Watches mission.phase transitions.
 */
export function MissionEventLog() {
  const phase = useMissionStore((s) => s.mission.phase)
  const [entries, setEntries] = useState<LogEntry[]>([])
  const lastPhase = useRef<MissionPhase>('idle')
  const idRef = useRef(0)

  useEffect(() => {
    if (phase === lastPhase.current) return
    lastPhase.current = phase
    if (phase === 'idle') { setEntries([]); return }
    const def = PHASE_LOG[phase]
    if (!def) return
    setEntries((prev) => [
      { id: idRef.current++, ts: hhmmss(), kind: def.kind, text: def.text },
      ...prev,
    ].slice(0, 12))
  }, [phase])

  return (
    <Card dense className="h-full flex flex-col min-h-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Mission Log
        </span>
        <span className="text-[10px] tabular text-text-lo">{entries.length}</span>
      </div>
      <div className="mt-2 flex-1 min-h-0 overflow-y-auto">
        {entries.length === 0 ? (
          <div className="py-3 text-[12px] text-text-lo">
            No mission running — click Start Task.
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {entries.map((e) => (
              <div key={e.id} className="grid grid-cols-[auto_auto_1fr] items-center gap-2 text-[12px]">
                <span className="tabular text-[10px] text-text-faint">{e.ts}</span>
                <Dot color={KIND_COLOR[e.kind]} size={6} glow={4} />
                <span className="text-text-md">{e.text}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}
