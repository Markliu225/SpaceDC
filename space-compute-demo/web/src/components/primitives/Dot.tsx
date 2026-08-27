/**
 * <Dot /> — every status indicator on the screen runs through here.
 * No glow by default: the indicator is a flat disc. A caller may still pass
 * `glow` for a soft halo, but chrome should not (design rule: no outer glows).
 *
 * Used by: header LIVE pill, donut legend, event log rows, satellite
 * markers, system health rows.
 */
export interface DotProps {
  color: string
  /** Diameter in px. Default 8. */
  size?: number
  /** Glow radius in px. Default 0 (no halo). */
  glow?: number
  /** Enable the live-pulse breathing animation. */
  pulse?: boolean
  className?: string
}

export function Dot({
  color,
  size = 8,
  glow = 0,
  pulse,
  className = '',
}: DotProps) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block rounded-full ${pulse ? 'animate-live-pulse' : ''} ${className}`}
      style={{
        width: size,
        height: size,
        background: color,
        boxShadow: glow > 0 ? `0 0 ${glow}px ${color}` : undefined,
      }}
    />
  )
}
