import { useEffect, useRef, useState } from 'react'

/**
 * <Num /> — the discipline that separates "mission control" from "admin
 * template". Every number on screen passes through here, which means:
 *   - JetBrains Mono + tabular-nums (no column jitter when value changes)
 *   - 400 ms count-up lerp when value changes (respect prefers-reduced-motion)
 *   - Locale-formatted thousands separators when integer >= 1000
 *
 * The component itself returns a <span>; callers decide font-size + color.
 */
export interface NumProps {
  value: number | string
  /** Decimal places. Ignored if `value` is already a string. */
  digits?: number
  /** Disable the count-up animation. Use for sparkline `current` values that
   *  tick every second — we don't want them lerping per tick. */
  animate?: boolean
  /** Add thousands separators. Default true for ints with abs >= 1000. */
  group?: boolean
  className?: string
}

function fmt(n: number, digits: number, group: boolean): string {
  if (Number.isNaN(n)) return '—'
  const abs = Math.abs(n)
  // Group only when meaningful — never on already-fractional small numbers.
  const useGroup = group && abs >= 1000
  const opts: Intl.NumberFormatOptions = {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: useGroup,
  }
  return new Intl.NumberFormat('en-US', opts).format(n)
}

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function Num({
  value,
  digits = 0,
  animate = true,
  group = true,
  className = '',
}: NumProps) {
  // If a string is passed straight through, render as-is.
  if (typeof value === 'string') {
    return (
      <span className={`font-mono tabular ${className}`}>{value}</span>
    )
  }

  const target = value
  const [display, setDisplay] = useState<number>(target)
  const fromRef = useRef<number>(target)
  const startRef = useRef<number>(0)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    if (!animate || prefersReducedMotion()) {
      setDisplay(target)
      return
    }
    fromRef.current = display
    startRef.current = performance.now()
    const duration = 400
    const tick = (now: number) => {
      const t = Math.min(1, (now - startRef.current) / duration)
      // ease-out cubic.
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplay(fromRef.current + (target - fromRef.current) * eased)
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }
    cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
    // We intentionally only restart when target changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, animate])

  return (
    <span className={`font-mono tabular ${className}`}>
      {fmt(display, digits, group)}
    </span>
  )
}
