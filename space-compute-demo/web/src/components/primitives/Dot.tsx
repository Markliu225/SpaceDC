/**
 * <Dot /> — every status indicator on the screen runs through here.
 * Glow MUST be a box-shadow tied to the color (per design brief).
 *
 * Used by: header LIVE pill, donut legend, event log rows, satellite
 * markers, system health rows.
 */
export interface DotProps {
  color: string
  /** Diameter in px. Default 8. */
  size?: number
  /** Glow radius in px. Default 6. */
  glow?: number
  /** Enable the live-pulse breathing animation. */
  pulse?: boolean
  className?: string
}

export function Dot({
  color,
  size = 8,
  glow = 6,
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
        boxShadow: `0 0 ${glow}px ${color}`,
      }}
    />
  )
}
