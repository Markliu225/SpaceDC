/**
 * Isometric satellite illustration — pure SVG, glow vibe.
 * Used by SelectedSatellite (left column). Floats via animate-float-y.
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
      <defs>
        <linearGradient id="sat-bus" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#3B9EFF" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#1B3A6F" />
        </linearGradient>
        <linearGradient id="sat-panel" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#0F1E3A" />
          <stop offset="100%" stopColor="#040A18" />
        </linearGradient>
        <filter id="sat-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.5" />
        </filter>
      </defs>

      {/* Soft accent halo behind the bus */}
      <ellipse cx="60" cy="60" rx="40" ry="22" fill="#3B9EFF" opacity="0.10" filter="url(#sat-glow)" />

      {/* Left panel */}
      <g transform="translate(8 38) skewY(-12)">
        <rect width="36" height="40" fill="url(#sat-panel)" stroke="#3B9EFF" strokeOpacity="0.4" strokeWidth="0.5" />
        {[0, 1, 2, 3, 4].map((i) => (
          <line key={i} x1={(i + 1) * 7} y1="0" x2={(i + 1) * 7} y2="40" stroke="#3B9EFF" strokeOpacity="0.3" strokeWidth="0.5" />
        ))}
        <line x1="0" y1="20" x2="36" y2="20" stroke="#3B9EFF" strokeOpacity="0.3" strokeWidth="0.5" />
      </g>
      {/* Right panel */}
      <g transform="translate(76 50) skewY(12)">
        <rect width="36" height="40" fill="url(#sat-panel)" stroke="#3B9EFF" strokeOpacity="0.4" strokeWidth="0.5" />
        {[0, 1, 2, 3, 4].map((i) => (
          <line key={i} x1={(i + 1) * 7} y1="0" x2={(i + 1) * 7} y2="40" stroke="#3B9EFF" strokeOpacity="0.3" strokeWidth="0.5" />
        ))}
        <line x1="0" y1="20" x2="36" y2="20" stroke="#3B9EFF" strokeOpacity="0.3" strokeWidth="0.5" />
      </g>

      {/* Central bus */}
      <g transform="translate(46 44)">
        <rect width="28" height="32" rx="2" fill="url(#sat-bus)" stroke="#7CC4FF" strokeOpacity="0.6" />
        <rect x="4" y="6" width="20" height="3" fill="#E8EEFB" opacity="0.4" />
        <rect x="4" y="12" width="14" height="2" fill="#E8EEFB" opacity="0.3" />
        <circle cx="22" cy="22" r="3" fill="#22D3EE" opacity="0.85" />
      </g>

      {/* Dish */}
      <g transform="translate(58 16)">
        <ellipse cx="0" cy="0" rx="8" ry="3" fill="#A6B0C4" opacity="0.4" />
        <line x1="0" y1="0" x2="0" y2="28" stroke="#7CC4FF" strokeWidth="1" opacity="0.7" />
      </g>

      {/* Emissive marker */}
      <circle cx="60" cy="60" r="3" fill="#22D3EE">
        <animate attributeName="opacity" values="0.6;1;0.6" dur="2.4s" repeatCount="indefinite" />
      </circle>
    </svg>
  )
}
