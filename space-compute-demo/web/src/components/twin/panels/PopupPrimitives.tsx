/**
 * Shared building blocks for the Twin module info popup. Lifted out of the
 * original popup file so all sub-panels render with identical rhythm
 * (header → bordered sections → label/value rows in mono-tabular numbers).
 */

import type { ReactNode } from 'react'

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-b border-border-weak px-3 py-2 last:border-b-0">
      <div className="mb-1 text-[9.5px] uppercase tracking-[0.14em] text-text-lo">
        {title}
      </div>
      <div className="flex flex-col gap-[3px]">{children}</div>
    </div>
  )
}

export function Row({
  label, value, unit, tone,
}: {
  label: string
  value: string
  unit?: string
  /** 'hot' subtly colours hot/warning values; 'accent' uses the HUD cyan. */
  tone?: 'hot' | 'accent'
}) {
  const valueClass =
    tone === 'hot'
      ? 'font-mono tabular-nums text-warn'
      : tone === 'accent'
      ? 'font-mono tabular-nums text-accent'
      : 'font-mono tabular-nums text-text-hi'
  return (
    <div className="flex items-baseline justify-between text-[11px]">
      <span className="text-text-md">{label}</span>
      <span className={valueClass}>
        {value}
        {unit ? <span className="ml-1 text-[9.5px] text-text-lo">{unit}</span> : null}
      </span>
    </div>
  )
}

/**
 * Card chrome — header with title + sub-meta + close (×), then the body
 * (sub-panel) below. Owned here so the three module kinds can't drift on
 * sizing / typography / close button.
 */
export function PopupChrome({
  title, subtitle, swatchColor, onClose, children,
}: {
  title: string
  subtitle?: string
  swatchColor?: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div className="pointer-events-auto w-[228px] rounded border border-border-med bg-card shadow-card">
      <div className="flex items-center justify-between border-b border-border-weak px-3 py-2">
        <div className="flex items-center gap-2 min-w-0">
          {swatchColor ? (
            <span
              className="h-3 w-3 shrink-0 rounded-sm ring-1 ring-white/10"
              style={{ background: swatchColor }}
              aria-hidden
            />
          ) : null}
          <div className="flex flex-col leading-tight min-w-0">
            <span className="text-[10px] uppercase tracking-[0.14em] text-text-md truncate">
              {title}
            </span>
            {subtitle ? (
              <span className="text-[11px] uppercase tracking-[0.06em] text-accent font-mono truncate">
                {subtitle}
              </span>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-text-lo hover:text-text-hi hover:bg-bg-cardHi"
        >
          <span className="text-[13px] leading-none">×</span>
        </button>
      </div>
      {children}
    </div>
  )
}
