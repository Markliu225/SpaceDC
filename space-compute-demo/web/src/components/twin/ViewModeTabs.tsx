import { Box, Cpu, Thermometer, Zap, type LucideIcon } from 'lucide-react'

export type TwinViewMode = 'structure' | 'power' | 'thermal' | 'compute'

interface ViewModeTabsProps {
  value: TwinViewMode
  onChange: (mode: TwinViewMode) => void
}

interface ModeDef {
  id: TwinViewMode
  label: string
  icon: LucideIcon
  /** Only Structure is wired up in P1; the rest are placeholders. */
  enabled: boolean
}

const MODES: ModeDef[] = [
  { id: 'structure', label: 'Structure', icon: Box,         enabled: true  },
  { id: 'power',     label: 'Power',     icon: Zap,         enabled: false },
  { id: 'thermal',   label: 'Thermal',   icon: Thermometer, enabled: false },
  { id: 'compute',   label: 'Compute',   icon: Cpu,         enabled: false },
]

/**
 * ViewModeTabs — 4 mutually-exclusive view buttons. Only Structure is
 * functional in Phase 1; the other three render with a "Soon" badge and
 * are click-disabled. Hook wiring is local to SatelliteTwinPage.
 */
export function ViewModeTabs({ value, onChange }: ViewModeTabsProps) {
  return (
    <div className="flex items-center gap-1 rounded border border-border-weak bg-bg-inset/60 p-0.5">
      {MODES.map((m) => {
        const Icon     = m.icon
        const selected = m.id === value
        return (
          <button
            key={m.id}
            type="button"
            disabled={!m.enabled}
            onClick={() => m.enabled && onChange(m.id)}
            className={[
              'relative flex items-center gap-1.5 rounded px-2 py-1 text-[11px] uppercase tracking-[0.08em] transition-colors',
              selected
                ? 'bg-accent/20 text-text-hi ring-1 ring-accent/40'
                : m.enabled
                  ? 'text-text-md hover:bg-bg-cardHi'
                  : 'text-text-faint cursor-not-allowed',
            ].join(' ')}
          >
            <Icon size={12} strokeWidth={1.8} />
            {m.label}
            {!m.enabled && (
              <span className="ml-1 rounded bg-bg-card px-1 text-[8px] uppercase tracking-[0.10em] text-text-lo">
                Soon
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
