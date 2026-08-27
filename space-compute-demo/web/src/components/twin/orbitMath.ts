/** Shared constants + pure helpers for the real-orbit views (MiniOrbitHud,
 *  TwinOrbitFallback). Kept component-free so react-refresh stays happy. */

import { colors } from '../../design/tokens'

export const EARTH_RADIUS_KM = 6378.137
export const SIDEREAL_DAY_S = 86164.0905
// NOTE: there is deliberately no sun-direction constant here. The sun and GMST
// come from the backend broadcast via `hooks/useSkyFrame` — see that file for
// why a hard-coded direction was 141.3 degrees wrong.

// HUD colours route through the design tokens so the orbit views follow the
// single accent hue: base = accent, "hot" (selected / tracked) = text.hi —
// one hue, two lightnesses, no second cyan. Names kept for call sites.
export const HUD_CYAN     = colors.accent
export const HUD_CYAN_HOT = colors.text.hi
export const HUD_WARN     = colors.warn

/** ECI (z = north pole) → Three.js display coords (Y-up).
 *  Display +Y = ECI +Z, so a +GMST rotation about display +Y increases right
 *  ascension — the correct sense for spinning the Earth under an inertial sun.
 *  Shared with the Overview globe (`components/overview/earth/*`): every ECI
 *  quantity that reaches a 3D scene — satellite, ring, or sun — goes through
 *  THIS function, which is what makes "ring on the terminator" true by
 *  construction instead of by coincidence. */
export function eciToDisplay([x, y, z]: [number, number, number]): [number, number, number] {
  return [x, z, -y]
}
