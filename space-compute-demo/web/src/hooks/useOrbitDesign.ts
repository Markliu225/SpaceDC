import { useCallback, useEffect, useRef, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type {
  CommsBand, CommsBandsResponse, GroundTargetState,
  GroundVisibilityResponse, OrbitDesignInfo,
} from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://localhost:8001'

/** The designer's editable fields — mirrors POST /orbit_design. */
export interface OrbitDesignDraft {
  altitude_km: number
  eccentricity: number
  inclination_deg: number
  raan_deg: number
  arg_perigee_deg: number
  mean_anomaly_deg: number
  planes: number
  sats_per_plane: number
  phasing: number
}

export const DESIGN_DEFAULTS: OrbitDesignDraft = {
  altitude_km: 550, eccentricity: 0.001, inclination_deg: 53,
  raan_deg: 0, arg_perigee_deg: 0, mean_anomaly_deg: 0,
  planes: 3, sats_per_plane: 8, phasing: 1,
}

/** Ground-station comms config (Overview config step). */
export interface GroundConfig {
  elevation_mask_deg: number
  band: string
  solar_bin: number
}

export const GROUND_CONFIG_DEFAULTS: GroundConfig = {
  elevation_mask_deg: 10, band: 'X', solar_bin: 10,
}

/**
 * useOrbitDesign — data source + actions for the Overview orbit designer and
 * ground-station comms config.
 *
 * `info` is the ACTIVE constellation's six classical elements + Walker
 * parameters. `apply()` POSTs the design and refetches the ring so every
 * view re-propagates. `bands` is the comms-band catalog. `setGroundTarget`
 * marks Singapore with the current comms config; live analytics (visibility,
 * bandwidth, elevation CDF, solar histogram) ride `lastState.ground_target`.
 */
export function useOrbitDesign() {
  const activeId = useTelemetryStore((s) => s.activeConstellationId)
  const groundTarget: GroundTargetState | null =
    useDemoStore((s) => s.lastState?.ground_target ?? null)

  const [info, setInfo] = useState<OrbitDesignInfo | null>(null)
  const [bands, setBands] = useState<CommsBand[]>([])
  const [visibility, setVisibility] = useState<GroundVisibilityResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [offline, setOffline] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refreshInfo = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/orbit_design`)
      if (!r.ok) throw new Error(`${r.status}`)
      setInfo((await r.json()) as OrbitDesignInfo)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => { void refreshInfo() }, [refreshInfo, activeId])

  // Comms-band catalog (static — fetch once).
  useEffect(() => {
    let cancelled = false
    fetch(`${BACKEND_HTTP}/comms_bands`)
      .then((r) => r.ok ? r.json() as Promise<CommsBandsResponse> : null)
      .then((d) => { if (!cancelled && d) setBands(d.bands) })
      .catch(() => { /* offline — band selector shows a minimal fallback */ })
    return () => { cancelled = true }
  }, [])

  const apply = useCallback(async (draft: OrbitDesignDraft): Promise<boolean> => {
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${BACKEND_HTTP}/orbit_design`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      })
      if (!r.ok) {
        const detail = await r.json().catch(() => null) as { detail?: string } | null
        setError(detail?.detail ?? `Design rejected (${r.status})`)
        return false
      }
      const body = (await r.json()) as OrbitDesignInfo
      setInfo(body)
      useTelemetryStore.getState().setActiveConstellation(body.active)
      // Refetch the ring detail EXPLICITLY: every design registers under the
      // same 'custom_design' id, so the id-keyed bridge effect would not
      // re-run on a REdesign and the fleet views would keep the old orbit.
      try {
        const dr = await fetch(`${BACKEND_HTTP}/constellations/${body.active}`)
        if (dr.ok) {
          useTelemetryStore.getState().setConstellationDetail(await dr.json())
        }
      } catch { /* bridge's id-keyed fetch remains the fallback */ }
      setVisibility(null)
      setOffline(false)
      return true
    } catch {
      setOffline(true)
      setError('Backend offline — start the FastAPI server (port 8001).')
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  /** Mark/clear the ground station with the comms config (or re-post config
   *  while already marked to change band / elevation / solar bin live). */
  const setGroundTarget = useCallback(async (
    enabled: boolean, config?: GroundConfig,
  ): Promise<boolean> => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/ground_target`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, ...(config ?? {}) }),  // defaults = Singapore
      })
      if (!enabled) setVisibility(null)
      return r.ok
    } catch {
      setOffline(true)
      return false
    }
  }, [])

  const analyze = useCallback(async (): Promise<boolean> => {
    setAnalyzing(true)
    setError(null)
    try {
      const r = await fetch(`${BACKEND_HTTP}/ground_visibility?orbits=1`)
      if (!r.ok) {
        const detail = await r.json().catch(() => null) as { detail?: string } | null
        setError(detail?.detail ?? `Analysis failed (${r.status})`)
        return false
      }
      setVisibility((await r.json()) as GroundVisibilityResponse)
      return true
    } catch {
      setOffline(true)
      return false
    } finally {
      setAnalyzing(false)
    }
  }, [])

  return {
    info, bands, groundTarget, visibility,
    busy, analyzing, offline, error,
    refreshInfo, apply, setGroundTarget, analyze,
  }
}

/** One coverage sample: visible-sat count + aggregate bandwidth at a tick. */
export interface CoverageSample {
  visible: number
  mbps: number
}

const COVERAGE_LEN = 120

/**
 * useCoverageHistory — a rolling window of ground-station visibility +
 * bandwidth, accumulated from the broadcast state (1 Hz). Feeds the Coverage
 * tab's line charts. Resets when the ground target is cleared or the sim
 * resets (sim_time_s goes backwards).
 */
export function useCoverageHistory(): CoverageSample[] {
  const [series, setSeries] = useState<CoverageSample[]>([])
  const lastSimRef = useRef<number>(-1)
  // Identity of the fleet these samples describe — a constellation switch OR
  // a same-id custom redesign (design_rev bumps) starts a fresh window so two
  // different fleets' visibility are never conflated in the chart.
  const fleetKeyRef = useRef<string>('')

  useEffect(() => {
    return useDemoStore.subscribe((s, prev) => {
      if (s.lastState === prev.lastState) return
      const st = s.lastState
      const gt = st?.ground_target
      const simT = st?.sim_time_s ?? 0
      if (!gt?.enabled) {
        lastSimRef.current = -1
        fleetKeyRef.current = ''
        setSeries((cur) => (cur.length ? [] : cur))
        return
      }
      const c = st?.constellation
      const fleetKey = `${c?.constellation_id ?? ''}:${c?.design_rev ?? 0}`
      const fleetChanged = fleetKey !== fleetKeyRef.current
      fleetKeyRef.current = fleetKey
      // One sample per new sim-second; reset on a backwards jump (sim reset)
      // or a fleet change (constellation switch / redesign).
      if (!fleetChanged && simT === lastSimRef.current) return
      const reset = fleetChanged || simT < lastSimRef.current
      lastSimRef.current = simT
      const sample: CoverageSample = { visible: gt.visible_sats, mbps: gt.aggregate_mbps }
      setSeries((cur) => {
        const base = reset ? [] : cur
        const next = base.length >= COVERAGE_LEN ? base.slice(1) : base.slice()
        next.push(sample)
        return next
      })
    })
  }, [])

  return series
}
