import { ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

interface ConfigDropdownOption<T extends string> {
  id: T
  label: string
  /** Right-aligned sub-text (e.g. "0.22 η · 2.5 kg/m²"). */
  meta?: string
  /** Color swatch shown left of the label. */
  swatch?: string
}

interface ConfigDropdownProps<T extends string> {
  label: string
  value: T
  options: ConfigDropdownOption<T>[]
  onChange: (v: T) => void
  /** Optional icon shown left of the label (lucide icon component). */
  icon?: ReactNode
  /** 'sm' (default) is the dense Configurator rail; 'md' is the satellite
   *  builder, which has a whole page to spend and needs readable type. */
  size?: 'sm' | 'md'
}

const SIZES = {
  sm: { label: 'text-[10px]', value: 'text-[12px] px-2 py-1',   option: 'text-[12px] px-2 py-1.5', meta: 'text-[10px]' },
  md: { label: 'text-[12px]', value: 'text-[14px] px-2.5 py-2', option: 'text-[13px] px-2.5 py-2', meta: 'text-[12px]' },
} as const

/**
 * ConfigDropdown — single-select picker styled to match SatelliteSelector.
 * Listbox absolutely positioned below the trigger; click-outside closes.
 *
 * Used by the twin page Configurator for GPU / solar material / solar size
 * / radiator material / radiator size — 5 instances. Generic over the
 * option id type so each call is type-safe (e.g. GpuType for the GPU one).
 */
export function ConfigDropdown<T extends string>({
  label, value, options, onChange, icon, size = 'sm',
}: ConfigDropdownProps<T>) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const sz = SIZES[size]

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const selected = options.find((o) => o.id === value) ?? options[0]
  // Options can be async (e.g. the workload profiles fetch) — render nothing
  // rather than crash the whole configurator rail on an empty list.
  if (!selected) return null

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <span className={`${sz.label} uppercase tracking-[0.10em] text-text-lo`}>
          {label}
        </span>
      </div>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full items-center justify-between gap-2 rounded border border-border-weak bg-bg-inset/60 ${sz.value} text-text-hi hover:border-border-med`}
      >
        <span className="flex items-center gap-2 min-w-0">
          {selected.swatch && (
            <span
              className="h-3 w-3 shrink-0 rounded-sm ring-1 ring-white/10"
              style={{ background: selected.swatch }}
            />
          )}
          <span className="truncate">{selected.label}</span>
        </span>
        <ChevronDown size={12} strokeWidth={1.5} className="shrink-0 text-text-md" />
      </button>
      {open && (
        <ul
          role="listbox"
          className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-y-auto rounded border border-border-med bg-card shadow-card"
        >
          {options.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                onClick={() => { onChange(o.id); setOpen(false) }}
                className={[
                  'flex w-full items-center gap-2 text-left transition-colors', sz.option,
                  o.id === value ? 'bg-accent/15 text-text-hi' : 'text-text-md hover:bg-bg-card-hi',
                ].join(' ')}
              >
                {o.swatch && (
                  <span
                    className="h-3 w-3 shrink-0 rounded-sm ring-1 ring-white/10"
                    style={{ background: o.swatch }}
                  />
                )}
                <span className="flex-1 min-w-0 truncate">{o.label}</span>
                {o.meta && (
                  <span className={`${sz.meta} tabular text-text-lo`}>{o.meta}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
