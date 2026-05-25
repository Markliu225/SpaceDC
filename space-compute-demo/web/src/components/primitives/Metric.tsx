import type { ReactNode } from 'react'
import { Num } from './Num'

/**
 * <Metric /> — shared typography for KPI tiles AND for the SatParamsGrid.
 * The brief specifies different sizes (KPI 30px vs param 14px), so callers
 * pick a `size` variant. Everything else (label uppercase + spacing, unit
 * muted, sub-text smaller + faint) is centralized here.
 */
export interface MetricProps {
  /** Uppercased label above the value. */
  label: string
  /** Numeric or string value. Numbers get count-up + tabular-nums. */
  value: number | string
  /** Unit suffix rendered muted next to the value (e.g. "W", "Mbps", "%"). */
  unit?: string
  /** Decimal places for numeric values. */
  digits?: number
  /** Sub-text rendered below in a fainter color. */
  sub?: ReactNode
  /** Visual size variant. */
  size?: 'kpi' | 'param'
  /** Color tone for the value (default text.hi). */
  tone?: 'hi' | 'ok' | 'warn' | 'err' | 'accent'
  /** Disable count-up (use for high-tick-rate metrics). */
  animate?: boolean
}

const TONE = {
  hi:     'text-text-hi',
  ok:     'text-ok',
  warn:   'text-warn',
  err:    'text-err',
  accent: 'text-accent',
} as const

export function Metric({
  label,
  value,
  unit,
  digits = 0,
  sub,
  size = 'kpi',
  tone = 'hi',
  animate = true,
}: MetricProps) {
  if (size === 'kpi') {
    return (
      <div className="flex flex-col">
        <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          {label}
        </div>
        <div className="mt-2 flex items-baseline">
          <Num
            value={value}
            digits={digits}
            animate={animate}
            className={`text-[30px] leading-none font-semibold ${TONE[tone]}`}
          />
          {unit && (
            <span className="ml-1 text-[13px] text-text-md">{unit}</span>
          )}
        </div>
        {sub && (
          <div className="mt-2 text-[12px] text-text-lo">{sub}</div>
        )}
      </div>
    )
  }
  // Param row variant — used inside SatParamsGrid.
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[11px] uppercase tracking-[0.08em] text-text-lo">
        {label}
      </span>
      <span className="flex items-baseline">
        <Num
          value={value}
          digits={digits}
          animate={animate}
          className={`text-[14px] ${TONE[tone]}`}
        />
        {unit && (
          <span className="ml-1 text-[11px] text-text-lo">{unit}</span>
        )}
      </span>
    </div>
  )
}
