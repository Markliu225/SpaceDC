/** Shared constants + pure helpers for the real-orbit views (MiniOrbitHud,
 *  TwinOrbitFallback). Kept component-free so react-refresh stays happy. */

export const EARTH_RADIUS_KM = 6378.137
export const SIDEREAL_DAY_S = 86164.0905
// Must match services/constellations.py and hooks/useFleetPositions.ts.
export const SUN_DIR_ECI: [number, number, number] = [0.648, -0.648, 0.398]
export const HUD_CYAN     = '#3B9EFF'
export const HUD_CYAN_HOT = '#22D3EE'
export const HUD_WARN     = '#F59E0B'

/** ECI (z = north pole) → Three.js display coords (Y-up). */
export function eciToDisplay([x, y, z]: [number, number, number]): [number, number, number] {
  return [x, z, -y]
}
