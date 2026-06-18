import { useCallback } from 'react'
import { useDemoStore } from '../store/demoStore'
import type { TwinGeometry } from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://localhost:8001'

export const DEFAULT_GEOM: TwinGeometry = {
  solar_clusters_per_side: 2,
  radiator_long: 1.55,
  radiator_ratio: 2.5,
  version: 0,
}

// Clamp ranges mirror the backend (state_engine.set_twin_geometry) +
// gen_twin_satellite.py so the UI can disable out-of-range steps.
export const GEOM_RANGE = {
  solar_clusters_per_side: { min: 1, max: 8, step: 1 },
  radiator_long: { min: 0.3, max: 3.0, step: 0.15 },
  radiator_ratio: { min: 1.2, max: 6.0, step: 0.5 },
} as const

/**
 * useTwinGeometry — read the live deployable geometry (from the backend's
 * broadcast state) and POST changes to /twin_geometry, which regenerates the
 * USD model and bumps the version so Kit reloads. Falls back to defaults +
 * silent no-op when the backend is offline (fallback scene).
 */
export function useTwinGeometry() {
  const geom = useDemoStore((s) => s.lastState?.twin_geometry) ?? DEFAULT_GEOM

  const update = useCallback(async (patch: Partial<TwinGeometry>) => {
    try {
      await fetch(`${BACKEND_HTTP}/twin_geometry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
    } catch {
      /* backend offline — controls are inert in the local fallback */
    }
  }, [])

  return { geom, update }
}
