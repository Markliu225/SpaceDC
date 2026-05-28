import type { MissionPhase, MissionState } from '../types/messages'

/**
 * missionPlan — the 天数天算 single-task choreography timeline + the pure
 * function that turns "seconds since Start" into a MissionState. Used by
 * the Phase-1 local mock driver; the backend MissionEngine (Phase 2)
 * reproduces the same beats so the hand-off is invisible.
 */

export interface PhaseDef {
  phase: Exclude<MissionPhase, 'idle'>
  label: string
  durationS: number
}

export const PHASE_PLAN: PhaseDef[] = [
  { phase: 'acquire',  label: 'AOI Acquired', durationS: 2 },
  { phase: 'capture',  label: 'Capturing',    durationS: 3 },
  { phase: 'route',    label: 'ISL Routing',  durationS: 4 },
  { phase: 'compute',  label: 'Inferencing',  durationS: 5 },
  { phase: 'downlink', label: 'Downlinking',  durationS: 3 },
  { phase: 'deliver',  label: 'Delivered',    durationS: 2 },
]

export const TOTAL_MISSION_S = PHASE_PLAN.reduce((a, p) => a + p.durationS, 0)

export const RAW_DATA_MB = 5120
export const RESULT_MB   = 2
export const TARGETS_FOUND = 7
/** Static caption only — what the same task would cost via 天数地算. */
export const GROUND_COMPUTE_REF_S = 2460

/** AOI + default ground station for the demo (Pacific NW open ocean). */
export const DEFAULT_AOI = { lat: 38.0, lon: -145.0 }

export interface GroundStation {
  id: string
  label: string
  lat: number
  lon: number
}

export const GROUND_STATIONS: GroundStation[] = [
  { id: 'GS-SVALBARD',  label: 'Svalbard',  lat: 78.2, lon: 15.4 },
  { id: 'GS-REYKJAVIK', label: 'Reykjavik', lat: 64.1, lon: -21.9 },
  { id: 'GS-GUAM',      label: 'Guam',      lat: 13.4, lon: 144.8 },
]

export interface MissionCastInput {
  sensor_idx: number
  hub_idx: number
  ground: GroundStation
}

/** label for a phase, including idle. */
export function phaseLabel(phase: MissionPhase): string {
  if (phase === 'idle') return 'Idle'
  return PHASE_PLAN.find((p) => p.phase === phase)?.label ?? phase
}

/** Index of a phase in the ordered plan (idle = -1). */
export function phaseIndex(phase: MissionPhase): number {
  return PHASE_PLAN.findIndex((p) => p.phase === phase)
}

/**
 * Resolve the mission state at `t` seconds after Start. Pure — no clocks,
 * no side effects. Past the final phase it pins to a completed `deliver`.
 */
export function missionStateAt(t: number, cast: MissionCastInput): MissionState {
  // Walk the plan accumulating durations to find the active phase.
  let acc = 0
  let activePhase: PhaseDef = PHASE_PLAN[0]
  let phaseStart = 0
  let done = false
  for (const def of PHASE_PLAN) {
    if (t < acc + def.durationS) {
      activePhase = def
      phaseStart = acc
      break
    }
    acc += def.durationS
    // If we walked off the end, the mission is complete.
    if (def === PHASE_PLAN[PHASE_PLAN.length - 1]) {
      activePhase = def
      phaseStart = acc - def.durationS
      done = t >= TOTAL_MISSION_S
    }
  }

  const progress = done
    ? 1
    : Math.max(0, Math.min(1, (t - phaseStart) / activePhase.durationS))

  // Data volume: full raw through capture/route; eases 5120 → 2 during
  // compute; result-sized afterwards.
  let data_volume_mb = 0
  const phase = activePhase.phase
  if (phase === 'capture' || phase === 'route') {
    data_volume_mb = RAW_DATA_MB
  } else if (phase === 'compute') {
    // Exponential-feel shrink so the 2500× drop reads on a log bar.
    const k = progress
    data_volume_mb = RAW_DATA_MB * Math.pow(RESULT_MB / RAW_DATA_MB, k)
  } else if (phase === 'downlink' || phase === 'deliver') {
    data_volume_mb = RESULT_MB
  }

  // Targets roll up during compute, frozen after.
  let targets_found = 0
  if (phase === 'compute') targets_found = Math.round(TARGETS_FOUND * progress)
  else if (phase === 'downlink' || phase === 'deliver') targets_found = TARGETS_FOUND

  // Elapsed since capture start (acquire doesn't count — capture is t≥2).
  const captureStart = PHASE_PLAN[0].durationS // acquire duration
  const elapsed_s = Math.max(0, Math.min(t, TOTAL_MISSION_S) - captureStart)

  return {
    active: !done,
    phase,
    phase_progress: progress,
    elapsed_s,
    data_volume_mb,
    targets_found,
    sensor_idx: cast.sensor_idx,
    hub_idx: cast.hub_idx,
    aoi_lat: DEFAULT_AOI.lat,
    aoi_lon: DEFAULT_AOI.lon,
    ground_lat: cast.ground.lat,
    ground_lon: cast.ground.lon,
    ground_id: cast.ground.id,
  }
}

/** Great-circle distance proxy (radians) between two lat/lon degrees. */
export function angularDist(latA: number, lonA: number, latB: number, lonB: number): number {
  const toR = Math.PI / 180
  const a1 = latA * toR, a2 = latB * toR
  const dLon = (lonB - lonA) * toR
  const cosd = Math.sin(a1) * Math.sin(a2) + Math.cos(a1) * Math.cos(a2) * Math.cos(dLon)
  return Math.acos(Math.max(-1, Math.min(1, cosd)))
}
