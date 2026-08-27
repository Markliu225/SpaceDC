import { useMemo } from 'react'
import { useTelemetryStore } from '../store/useTelemetryStore'
import { useSkyFrame, type SkyFrame } from './useSkyFrame'
import type { ConstellationDetail } from '../types/messages'

export interface FleetSatPosition {
  idx: number
  planeIdx: number
  slotIdx: number
  /** ECI km position at sim_now. */
  eci: [number, number, number]
  /** Sub-satellite point in degrees (geographic, ECEF-corrected). */
  lat: number
  lon: number
  /** Altitude above mean Earth radius, km. */
  altitudeKm: number
  /** Sunlit / dark side flag — dot(pos_eci, sun_unit_teme) >= -0.05 ⇒ sunlit,
   *  against the sun direction BROADCAST for this tick. `true` while the sky
   *  frame is unknown (offline): an unknown sun must not manufacture a
   *  terminator. */
  sunlit: boolean
}

const EARTH_RADIUS_KM = 6378.137

/** Linear interpolation between ring samples for a smooth ground track. */
function sampleRing(
  ring: ConstellationDetail['ring_eci_km'],
  phase: number,
): [number, number, number] {
  const n = ring.length
  const u = ((phase % 1) + 1) % 1
  const fIdx = u * n
  const i0 = Math.floor(fIdx) % n
  const i1 = (i0 + 1) % n
  const t = fIdx - Math.floor(fIdx)
  const [x0, y0, z0] = ring[i0]
  const [x1, y1, z1] = ring[i1]
  return [
    x0 + (x1 - x0) * t,
    y0 + (y1 - y0) * t,
    z0 + (z1 - z0) * t,
  ]
}

/** Rotate a 3-vector about +Z by angle (radians). */
function rotZ(v: [number, number, number], a: number): [number, number, number] {
  const c = Math.cos(a)
  const s = Math.sin(a)
  return [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]]
}

/**
 * useFleetPositions — derives every sat's ECI km position and sub-sat
 * lat/lon from the constellation's base orbit ring + Walker offsets.
 *
 * Math (matches services/constellations.py construction):
 *   For sat (plane=k, slot=j) of an (planes=P × sats_per_plane=S, phasing=f)
 *   Walker pattern with period τ:
 *     time offset along ring  = j·(τ/S) + k·f·(τ/(P·S))
 *     plane rotation about +Z = k·(360°/P)
 *
 *   sim_now (ring time) = sim_time_s · time_scale
 *
 *   pos_eci(k,j) = RotZ(plane_angle) · ring[ wrap((sim_now + offset)/τ) ]
 *
 * ECEF correction: rotates ECI by -GMST about +Z so the ground track sweeps
 * west at Earth's sidereal rate; otherwise the constellation would appear
 * locked above the same longitude band forever. GMST is the value BROADCAST
 * with this tick (`sky.gmstRad`), not a ramp integrated from zero — the old
 * `simNow/SIDEREAL_DAY_S·2π` started at 0 while true GMST at mission start is
 * 151.287°, i.e. every sub-satellite longitude was off by a constant 151.29°.
 */
function computeSatPosition(
  detail: ConstellationDetail, simTimeS: number, idx: number, sky: SkyFrame,
): FleetSatPosition {
  const { ring_eci_km, planes, sats_per_plane, phasing, period_s, time_scale } = detail
  const T = planes * sats_per_plane
  const simNow = simTimeS * time_scale
  const gmst = sky.gmstRad

  const k = Math.floor(idx / sats_per_plane)
  const j = idx % sats_per_plane
  const planeAngle = (k * 2 * Math.PI) / planes
  const slotOffset = j * (period_s / sats_per_plane)
    + k * phasing * (period_s / T)
  const phase = ((simNow + slotOffset) / period_s) % 1
  const ringPt = sampleRing(ring_eci_km, phase)
  const eci = rotZ(ringPt, planeAngle)

  // ECI → ECEF for the sub-sat point.
  const ecef = rotZ(eci, -gmst)
  const r = Math.hypot(ecef[0], ecef[1], ecef[2]) || 1
  const lat = (Math.asin(ecef[2] / r) * 180) / Math.PI
  const lon = (Math.atan2(ecef[1], ecef[0]) * 180) / Math.PI

  // Sunlit test stays in ECI — the sun direction is inertial, so it needs no
  // GMST correction, but it DOES need to be the broadcast one (same frame and
  // same instant as these ECI km) or the eclipse band sits on the wrong side
  // of the planet. Sun unknown ⇒ report sunlit rather than invent a shadow.
  const sun = sky.sunEci
  const sunlit = sun === null
    || (eci[0] * sun[0] + eci[1] * sun[1] + eci[2] * sun[2]) / r >= -0.05

  return {
    idx, planeIdx: k, slotIdx: j,
    eci, lat, lon,
    altitudeKm: r - EARTH_RADIUS_KM,
    sunlit,
  }
}

export function useFleetPositions(): FleetSatPosition[] {
  const detail   = useTelemetryStore((s) => s.constellationDetail)
  const simTimeS = useTelemetryStore((s) => s.sim_time_s)
  const sky      = useSkyFrame()

  return useMemo(() => {
    if (!detail || detail.ring_eci_km.length === 0) return []
    const total = detail.planes * detail.sats_per_plane
    return Array.from({ length: total }, (_, i) => computeSatPosition(detail, simTimeS, i, sky))
  }, [detail, simTimeS, sky])
}

/**
 * useSatPosition — ONE satellite's live position on an arbitrary clock.
 * The frame-rate orbit views (MiniOrbitHud reticle, TwinOrbitFallback) use
 * this with the smoothly-extrapolated clock: O(1) per frame, unlike
 * useFleetPositions which rebuilds the whole fleet (1500+ sats on the big
 * Walker presets) and must stay on the 1 Hz store clock.
 */
export function useSatPosition(idx: number, simTimeS: number): FleetSatPosition | null {
  const detail = useTelemetryStore((s) => s.constellationDetail)
  const sky    = useSkyFrame()
  return useMemo(() => {
    if (!detail || detail.ring_eci_km.length === 0) return null
    const total = detail.planes * detail.sats_per_plane
    const clamped = Math.max(0, Math.min(total - 1, idx))
    return computeSatPosition(detail, simTimeS, clamped, sky)
  }, [detail, simTimeS, idx, sky])
}
