import { useCallback, useEffect, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type {
  GroundTargetState, GroundVisibilityResponse, OrbitDesignInfo,
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

/**
 * useOrbitDesign — data source + actions for the Overview orbit designer.
 *
 * `info` is the ACTIVE constellation's six classical elements + Walker
 * parameters (GET /orbit_design, refetched whenever the active preset
 * changes — switching a preset in the selector updates the readout live).
 * `apply()` POSTs the draft: the backend synthesizes the reference TLE,
 * registers the design as the `custom_design` preset and activates it —
 * the 3D viewport / coverage map / fleet propagator all follow on the
 * next broadcast. Ground-target actions mark Singapore and fetch the
 * pass analysis; live visibility rides `lastState.ground_target`.
 */
export function useOrbitDesign() {
  const activeId = useTelemetryStore((s) => s.activeConstellationId)
  const groundTarget: GroundTargetState | null =
    useDemoStore((s) => s.lastState?.ground_target ?? null)

  const [info, setInfo] = useState<OrbitDesignInfo | null>(null)
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

  // The elements readout follows the ACTIVE constellation.
  useEffect(() => { void refreshInfo() }, [refreshInfo, activeId])

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
      // re-run on a REdesign and the fleet views would keep propagating the
      // previous orbit.
      try {
        const dr = await fetch(`${BACKEND_HTTP}/constellations/${body.active}`)
        if (dr.ok) {
          useTelemetryStore.getState().setConstellationDetail(await dr.json())
        }
      } catch { /* bridge's id-keyed fetch remains the fallback */ }
      // A new orbit invalidates any previous pass analysis.
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

  const setGroundTarget = useCallback(async (enabled: boolean): Promise<boolean> => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/ground_target`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),  // defaults = Singapore
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
    info, groundTarget, visibility,
    busy, analyzing, offline, error,
    refreshInfo, apply, setGroundTarget, analyze,
  }
}
