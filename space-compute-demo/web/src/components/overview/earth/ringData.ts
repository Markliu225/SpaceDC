/**
 * ringData — the Overview globe's ONLY source of orbit geometry.
 *
 * Everything here comes from the backend's propagated orbit samples; nothing
 * is synthesised. The module exists so `OrbitRibbons` (what is drawn) and
 * `Satellites` (what rides it) share one transform and cannot drift apart:
 * a sprite is always sampled from the very polyline its ribbon was built from.
 *
 * Frames:
 *   backend ECI (TEME, +Z = north pole, km)
 *     → / EARTH_RADIUS_KM      (Earth radius becomes 1 scene unit)
 *     → eciToDisplay           ([x, y, z] → [x, z, -y], three.js Y-up)
 *
 * The rings are INERTIAL — they must not be parented to the spinning Earth
 * mesh. Earth spin is GMST about display +Y (see Earth.tsx).
 */

import { useMemo } from 'react'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { EARTH_RADIUS_KM, eciToDisplay } from '../../twin/orbitMath'
import type { ConstellationDetail } from '../../../types/messages'

export type Vec3 = [number, number, number]

/**
 * `rings_eci_km` — one propagated ring per plane (Walker) or per shell (SSO) —
 * is served alongside the legacy single `ring_eci_km`. It is read structurally
 * so this module keeps compiling and running against a backend, or a
 * `types/messages.ts`, that predates it.
 */
type DetailWithRings = ConstellationDetail & { rings_eci_km?: number[][][] }

export interface ConstellationRingData {
  /** One closed polyline per plane / shell in display units (Earth radius = 1).
   *  EMPTY when no constellation detail is loaded — the scene then draws no
   *  rings at all rather than inventing decorative ones. */
  rings: Vec3[][]
  /**
   * `backend` — every ring came from `rings_eci_km`, so ring k really is
   *   plane/shell k's own propagated orbit. This is what puts the SSO shells on
   *   ONE shared dawn–dusk plane at increasing altitudes instead of fanning
   *   them out.
   * `walker` — only the legacy base ring was available, so plane k is the base
   *   ring rotated by k·360/planes about ECI +Z. Correct for a Walker pattern,
   *   and identical to what `hooks/useFleetPositions.ts` does; it is WRONG for
   *   SSO, which is exactly why the backend now sends `rings_eci_km`.
   * `none` — nothing to draw.
   */
  source: 'backend' | 'walker' | 'none'
  /** The detail the rings were built from — carries the phasing parameters the
   *  satellite placement needs. Null when there is nothing loaded. */
  detail: ConstellationDetail | null
}

const EMPTY: ConstellationRingData = { rings: [], source: 'none', detail: null }

function toDisplayRing(ring: number[][]): Vec3[] {
  const inv = 1 / EARTH_RADIUS_KM
  return ring.map(([x, y, z]) => eciToDisplay([x * inv, y * inv, z * inv]))
}

/** Rotate an ECI sample about +Z (the Walker plane offset). */
function rotZ([x, y, z]: number[], c: number, s: number): number[] {
  return [x * c - y * s, x * s + y * c, z]
}

export function buildRingData(detail: DetailWithRings | null): ConstellationRingData {
  if (!detail) return EMPTY

  const backend = detail.rings_eci_km
  if (Array.isArray(backend) && backend.length > 0
      && backend.every((r) => Array.isArray(r) && r.length > 2)) {
    return { rings: backend.map(toDisplayRing), source: 'backend', detail }
  }

  const base = detail.ring_eci_km
  if (!Array.isArray(base) || base.length < 3) return EMPTY
  const planes = Math.max(1, Math.trunc(detail.planes) || 1)
  const rings = Array.from({ length: planes }, (_, k) => {
    const a = (k * 2 * Math.PI) / planes
    const c = Math.cos(a)
    const s = Math.sin(a)
    return toDisplayRing(base.map((p) => rotZ(p, c, s)))
  })
  return { rings, source: 'walker', detail }
}

/** Live orbit geometry for the active constellation. Rebuilds only when the
 *  constellation detail changes (preset swap / redesign), not per frame. */
export function useConstellationRings(): ConstellationRingData {
  const detail = useTelemetryStore((s) => s.constellationDetail)
  return useMemo(
    () => buildRingData(detail as DetailWithRings | null),
    [detail],
  )
}

/** Linear interpolation between ring samples — same scheme as
 *  `hooks/useFleetPositions.ts::sampleRing`, in display units. */
function sampleRing(ring: Vec3[], phase: number): Vec3 {
  const n = ring.length
  const u = ((phase % 1) + 1) % 1
  const f = u * n
  const i0 = Math.floor(f) % n
  const i1 = (i0 + 1) % n
  const t = f - Math.floor(f)
  const a = ring[i0]
  const b = ring[i1]
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ]
}

/**
 * Display position of fleet index `idx` at sim second `simTimeS`.
 *
 * Phasing math mirrors `hooks/useFleetPositions.ts` (which mirrors
 * `services/constellations.py`): satellite (plane k, slot j) of a
 * (planes P × sats_per_plane S, phasing f) pattern with period τ sits at
 *
 *     phase = ((sim_t · time_scale) + j·τ/S + k·f·τ/(P·S)) / τ   (mod 1)
 *
 * along ITS OWN plane's ring — which is the difference that matters here: the
 * plane offset is expressed by picking ring k, not by rotating ring 0, so an
 * SSO fleet lands on the shared dawn–dusk plane instead of fanning out.
 *
 * Returns null when there is no geometry to sample.
 */
export function satDisplayPosition(
  data: ConstellationRingData, idx: number, simTimeS: number,
): Vec3 | null {
  const { rings, detail } = data
  if (!detail || rings.length === 0) return null
  const S = Math.max(1, Math.trunc(detail.sats_per_plane) || 1)
  const P = Math.max(1, Math.trunc(detail.planes) || 1)
  const tau = detail.period_s > 0 ? detail.period_s : 1
  const scale = detail.time_scale > 0 ? detail.time_scale : 1
  const k = Math.min(rings.length - 1, Math.floor(idx / S))
  const j = idx % S
  const slotOffset = j * (tau / S) + k * detail.phasing * (tau / (P * S))
  const phase = ((simTimeS * scale) + slotOffset) / tau
  return sampleRing(rings[k], phase)
}
