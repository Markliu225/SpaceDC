import { colors } from '../../design/tokens'

/**
 * Isometric satellite illustration — pure SVG, flat token colors, no glow.
 * Used by SelectedSatellite (left column). Static (no float / pulse).
 */
export function SatelliteIcon({ size = 96 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Satellite icon"
    >
      {/* Left panel */}
      <g transform="translate(8 38) skewY(-12)">
        <rect width="36" height="40" fill={colors.bg.inset} stroke={colors.accent} strokeOpacity="0.4" strokeWidth="0.5" />
        {[0, 1, 2, 3, 4].map((i) => (
          <line key={i} x1={(i + 1) * 7} y1="0" x2={(i + 1) * 7} y2="40" stroke={colors.accent} strokeOpacity="0.3" strokeWidth="0.5" />
        ))}
        <line x1="0" y1="20" x2="36" y2="20" stroke={colors.accent} strokeOpacity="0.3" strokeWidth="0.5" />
      </g>
      {/* Right panel */}
      <g transform="translate(76 50) skewY(12)">
        <rect width="36" height="40" fill={colors.bg.inset} stroke={colors.accent} strokeOpacity="0.4" strokeWidth="0.5" />
        {[0, 1, 2, 3, 4].map((i) => (
          <line key={i} x1={(i + 1) * 7} y1="0" x2={(i + 1) * 7} y2="40" stroke={colors.accent} strokeOpacity="0.3" strokeWidth="0.5" />
        ))}
        <line x1="0" y1="20" x2="36" y2="20" stroke={colors.accent} strokeOpacity="0.3" strokeWidth="0.5" />
      </g>

      {/* Central bus */}
      <g transform="translate(46 44)">
        <rect width="28" height="32" rx="2" fill={colors.accent} fillOpacity="0.55" stroke={colors.accentText} strokeOpacity="0.6" />
        <rect x="4" y="6" width="20" height="3" fill={colors.text.hi} opacity="0.4" />
        <rect x="4" y="12" width="14" height="2" fill={colors.text.hi} opacity="0.3" />
        <circle cx="22" cy="22" r="3" fill={colors.accentText} opacity="0.85" />
      </g>

      {/* Dish */}
      <g transform="translate(58 16)">
        <ellipse cx="0" cy="0" rx="8" ry="3" fill={colors.text.md} opacity="0.4" />
        <line x1="0" y1="0" x2="0" y2="28" stroke={colors.accentText} strokeWidth="1" opacity="0.7" />
      </g>

      {/* Status marker (static — the illustration is not a live indicator) */}
      <circle cx="60" cy="60" r="3" fill={colors.text.hi} opacity="0.85" />
    </svg>
  )
}
