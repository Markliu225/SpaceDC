/** Shared constants + pure helpers for the real-orbit views (MiniOrbitHud,
 *  TwinOrbitFallback). Kept component-free so react-refresh stays happy. */

import { colors } from '../../design/tokens'

export const EARTH_RADIUS_KM = 6378.137
export const SIDEREAL_DAY_S = 86164.0905
// Must match services/constellations.py and hooks/useFleetPositions.ts.
export const SUN_DIR_ECI: [number, number, number] = [0.648, -0.648, 0.398]
// HUD colours route through the design tokens so the orbit views follow the
// single accent hue: base = accent, "hot" (selected / tracked) = text.hi —
// one hue, two lightnesses, no second cyan. Names kept for call sites.
export const HUD_CYAN     = colors.accent
export const HUD_CYAN_HOT = colors.text.hi
export const HUD_WARN     = colors.warn

/** ECI (z = north pole) → Three.js display coords (Y-up). */
export function eciToDisplay([x, y, z]: [number, number, number]): [number, number, number] {
  return [x, z, -y]
}
