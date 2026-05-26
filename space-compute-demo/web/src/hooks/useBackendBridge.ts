import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useTelemetryStore } from '../store/useTelemetryStore'
import type { ConstellationPresetSummary, FleetSnapshot } from '../types/messages'

const BACKEND_HTTP = (import.meta.env.VITE_BACKEND_HTTP as string | undefined)
  ?? 'http://localhost:8001'

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
  const setPresets = useTelemetryStore((s) => s.setPresets)
  const applyFleet = useTelemetryStore((s) => s.applyFleet)
  const setActive  = useTelemetryStore((s) => s.setActiveConstellation)

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

  // Bridge demoStore.lastState.constellation -> telemetryStore.fleet.
  useEffect(() => {
    return useDemoStore.subscribe((s, prev) => {
      if (s.lastState === prev.lastState) return
      const c = (s.lastState as { constellation?: FleetSnapshot } | null)?.constellation
      if (c) applyFleet(c)
    })
  }, [applyFleet])
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
