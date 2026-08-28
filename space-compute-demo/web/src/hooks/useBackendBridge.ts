import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type {
  ConstellationDetail,
  ConstellationPresetSummary,
  FleetSnapshot,
  SatelliteConfig,
} from '../types/messages'

const BACKEND_HTTP = (import.meta.env.VITE_BACKEND_HTTP as string | undefined)
  ?? 'http://127.0.0.1:8001'

interface ConstellationsListResponse {
  active: string
  presets: ConstellationPresetSummary[]
}

/**
 * useBackendBridge — copies the parts of the demoStore WebSocket feed that
 * the Overview cares about (the constellation snapshot) into useTelemetryStore.
 *
 * Also fetches GET /constellations once so the selector can populate its
 * dropdown. The fetch is HTTP not WS because the preset catalog is static —
 * it's not worth pushing on every state_update.
 *
 * Exposes a `switchConstellation` action so the UI can POST to backend; the
 * resulting fleet snapshot will arrive via the next WS state_update tick.
 */
export function useBackendBridge() {
  const setPresets      = useTelemetryStore((s) => s.setPresets)
  const applyFleet      = useTelemetryStore((s) => s.applyFleet)
  const setActive       = useTelemetryStore((s) => s.setActiveConstellation)
  const setDetail       = useTelemetryStore((s) => s.setConstellationDetail)
  const activeId        = useTelemetryStore((s) => s.activeConstellationId)
  const setSatConfig    = useTelemetryStore((s) => s.setSatConfig)

  // One-shot preset fetch.
  useEffect(() => {
    let cancelled = false
    fetch(`${BACKEND_HTTP}/constellations`)
      .then((r) => r.json() as Promise<ConstellationsListResponse>)
      .then((d) => {
        if (cancelled) return
        setPresets(d.presets)
        setActive(d.active)
      })
      .catch(() => { /* backend offline — selector just shows empty list */ })
    return () => { cancelled = true }
  }, [setPresets, setActive])

  // Bridge demoStore.lastState.constellation -> telemetryStore.fleet,
  // lastState.satellite_config -> telemetryStore.satConfig, and re-base the
  // local sim clock onto the backend's sim_time_s so every consumer of the
  // shared clock (MiniOrbitHud orbit dot, fleet propagation, chart time
  // labels) runs in the SAME time frame as the physics engine instead of a
  // free-running local counter.
  useEffect(() => {
    return useDemoStore.subscribe((s, prev) => {
      if (s.lastState === prev.lastState) return
      type Echo = {
        constellation?: FleetSnapshot
        satellite_config?: SatelliteConfig
        sim_time_s?: number
      }
      const last = s.lastState as Echo | null
      if (last?.constellation)     applyFleet(last.constellation)
      if (last?.satellite_config)  setSatConfig(last.satellite_config)
      if (typeof last?.sim_time_s === 'number') {
        useTelemetryStore.getState().applyTick({ sim_time_s: last.sim_time_s })
      }
    })
  }, [applyFleet, setSatConfig])

  // Fetch full detail (Walker params + ring_eci_km) whenever the active
  // preset id changes. The Web fleet propagator needs the ring + phasing
  // to derive per-sat ECI without per-tick round-trips.
  useEffect(() => {
    if (!activeId) return
    let cancelled = false
    fetch(`${BACKEND_HTTP}/constellations/${activeId}`)
      .then((r) => r.ok ? r.json() as Promise<ConstellationDetail> : null)
      .then((d) => {
        if (cancelled || !d) return
        setDetail(d)
      })
      .catch(() => { /* backend offline — detail stays null, fleet propagator no-ops */ })
    return () => { cancelled = true }
  }, [activeId, setDetail])
}

/**
 * switchConstellation — POST /constellation/{id} and immediately optimistically
 * mark the new id as active so the selector UI reflects the change before
 * the next 1Hz WS state_update lands.
 */
export async function switchConstellation(id: string): Promise<boolean> {
  useTelemetryStore.getState().setActiveConstellation(id)
  try {
    const r = await fetch(`${BACKEND_HTTP}/constellation/${id}`, { method: 'POST' })
    return r.ok
  } catch {
    return false
  }
}
