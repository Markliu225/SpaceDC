import { useCallback, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import type { DesignPresetInfo, DesignsResponse } from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://127.0.0.1:8001'

/** Absolute URL for a design's preview thumbnail (backend-relative path). */
export function previewSrc(design: DesignPresetInfo): string {
  return `${BACKEND_HTTP}${design.preview_url}`
}

/**
 * useDesigns — the design-gallery data source. `refresh()` loads the preset
 * list from GET /designs (the caller decides when — DesignGallery calls it on
 * mount and again on each open); the live active design id comes from the
 * broadcast state.
 *
 * Applying a design is authoritative-only (no optimistic write): the backend
 * regenerates the USD, bumps the geometry version (Kit reloads the layer) and
 * broadcasts a state_update carrying the new config + design_id, which every
 * panel already listens to.
 */
export function useDesigns() {
  const [designs, setDesigns] = useState<DesignPresetInfo[]>([])
  const [fetchedActive, setFetchedActive] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [applying, setApplying] = useState<string | null>(null)

  // Live value wins over the one-shot fetch; before either arrives, null.
  const liveActive = useDemoStore((s) => s.lastState?.design_id)
  const activeId = liveActive ?? fetchedActive

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/designs`)
      if (!r.ok) throw new Error(`${r.status}`)
      const body = (await r.json()) as DesignsResponse
      setDesigns(body.designs)
      setFetchedActive(body.active)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  const applyDesign = useCallback(async (id: string): Promise<ApplyResult> => {
    setApplying(id)
    try {
      const r = await fetch(`${BACKEND_HTTP}/designs/${id}/apply`, { method: 'POST' })
      if (!r.ok) return { ok: false, regenerated: false }
      const body = (await r.json()) as { ok: boolean; regenerated: boolean }
      return { ok: body.ok === true, regenerated: body.regenerated === true }
    } catch {
      setOffline(true)
      return { ok: false, regenerated: false }
    } finally {
      setApplying(null)
    }
  }, [])

  return { designs, activeId, offline, applying, applyDesign, refresh }
}

export interface ApplyResult {
  /** The design switched (config + workload + physics now follow it). */
  ok: boolean
  /** The USD model regenerated too — false means the viewport still shows
   *  the previous geometry even though the physics switched. */
  regenerated: boolean
}
