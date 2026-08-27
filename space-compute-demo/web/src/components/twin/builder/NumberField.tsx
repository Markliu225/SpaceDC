import { useState } from 'react'

/**
 * NumberField — a typed numeric knob with ± nudges.
 *
 * The builder's panel sizes are real dimensions, not T-shirt sizes: a viewer
 * who wants a 4.7 m radiator should type 4.7 rather than hunt for the preset
 * that lands nearest. Typing is unconstrained while the field has focus (so
 * "1", "1.", "1.7" are all valid intermediate states) and the value is clamped
 * to [min, max] on commit — Enter, blur, or a ± click. An out-of-range or
 * unparseable entry snaps back to the last good value rather than silently
 * writing something the engine would clamp anyway.
 */
export function NumberField({
  label, value, onCommit, min, max, step, unit, decimals = 2, hint, disabled, disabledText,
}: {
  label: string
  value: number
  onCommit: (v: number) => void
  min: number
  max: number
  step: number
  unit?: string
  decimals?: number
  /** Secondary line under the field — what the number produces. */
  hint?: string
  disabled?: boolean
  disabledText?: string
}) {
  const fmt = (v: number) => (Number.isInteger(v) && decimals === 0
    ? String(v) : v.toFixed(decimals).replace(/\.?0+$/, ''))
  // `null` means "show the committed value" — the field only holds text of its
  // own while it is being edited, so a value changed from outside (a platform
  // switch, a ± click) needs no effect to sync it back.
  const [editing, setEditing] = useState<string | null>(null)
  const text = editing ?? fmt(value)

  const clamp = (v: number) => Math.min(max, Math.max(min, v))
  const round = (v: number) => Math.round(v * 1e4) / 1e4

  const commit = (raw: string) => {
    setEditing(null)
    const n = Number.parseFloat(raw)
    if (!Number.isFinite(n)) return          // unparseable — snap back
    const next = round(clamp(n))
    if (next !== value) onCommit(next)
  }

  const nudge = (dir: -1 | 1) => {
    setEditing(null)
    const next = round(clamp(value + dir * step))
    if (next !== value) onCommit(next)
  }

  const btn = 'flex h-7 w-7 shrink-0 items-center justify-center rounded border border-border-weak '
    + 'text-text-md hover:bg-bg-card-hi hover:text-text-hi disabled:opacity-30 disabled:cursor-not-allowed'

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[12px] uppercase tracking-[0.10em] text-text-lo">{label}</span>
      <div className="flex items-center gap-1.5">
        <button type="button" className={btn} aria-label={`decrease ${label}`}
                disabled={disabled || value <= min + 1e-9} onClick={() => nudge(-1)}>−</button>
        <div className={`flex min-w-0 flex-1 items-baseline gap-1 rounded border bg-bg-inset/60 px-2.5 py-1.5
                        ${disabled ? 'border-border-weak opacity-60' : 'border-border-weak focus-within:border-accent/70'}`}>
          {disabled ? (
            <span className="truncate font-mono text-[14px] text-text-lo">{disabledText ?? '—'}</span>
          ) : (
            <>
              <input
                type="text"
                inputMode="decimal"
                aria-label={label}
                value={text}
                onChange={(e) => setEditing(e.target.value)}
                onFocus={(e) => e.target.select()}
                onBlur={(e) => commit(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { commit((e.target as HTMLInputElement).value); (e.target as HTMLInputElement).blur() }
                  if (e.key === 'Escape') { setEditing(null); (e.target as HTMLInputElement).blur() }
                  if (e.key === 'ArrowUp') { e.preventDefault(); nudge(1) }
                  if (e.key === 'ArrowDown') { e.preventDefault(); nudge(-1) }
                }}
                className="w-full min-w-0 bg-transparent font-mono text-[14px] tabular-nums text-text-hi outline-none"
              />
              {unit && <span className="shrink-0 font-mono text-[12px] text-text-lo">{unit}</span>}
            </>
          )}
        </div>
        <button type="button" className={btn} aria-label={`increase ${label}`}
                disabled={disabled || value >= max - 1e-9} onClick={() => nudge(1)}>+</button>
      </div>
      <span className="flex items-baseline justify-between gap-2 text-[11px] text-text-lo">
        <span>{disabled ? '' : `${fmt(min)}–${fmt(max)}${unit ? ` ${unit}` : ''}`}</span>
        {hint && <span className="truncate font-mono text-text-lo">{hint}</span>}
      </span>
    </div>
  )
}
