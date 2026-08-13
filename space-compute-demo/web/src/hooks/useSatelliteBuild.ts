import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  GpuType,
  SatelliteAssetInfo,
  SatelliteBuildPreview,
  SatelliteBuildRequest,
  SatelliteConfig,
} from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://localhost:8001'

/** Deployable-geometry knobs the structure step edits. */
export interface BuildGeometry {
  solar_clusters_per_side: number
  radiator_long: number
  radiator_ratio: number
}

/** The satellite being built — staged entirely client-side. NOTHING reaches
 *  the live engine until Run (`submit`), which applies all four steps at
 *  once; until then the only backend traffic is the read-only dry-run. */
export interface BuildDraft {
  asset: string
  config: SatelliteConfig
  geometry: BuildGeometry
  slots: (GpuType | null)[]
  workload_profile: string
  attitude_mode: string
}

/** Bounds mirror state_engine.set_twin_geometry's clamps. */
export const BUILD_RANGE = {
  solar_clusters_per_side: { min: 1, max: 8, step: 1 },
  radiator_long:  { min: 0.3, max: 3.0, step: 0.05 },
  radiator_ratio: { min: 1.2, max: 6.0, step: 0.1 },
} as const

/** The satellite currently in orbit, when the builder opens on ITS platform —
 *  "rebuild" should start from what is flying, not from the crate. */
export interface LiveSeed {
  config?: SatelliteConfig
  geometry?: Partial<BuildGeometry>
  /** Fitted cards; empty/absent means the uniform `config.gpu` × `gpuCount`
   *  loadout every design preset flies, which we materialize into slots. */
  slots?: (GpuType | null)[]
  gpuCount?: number
  workload_profile?: string
  attitude_mode?: string
}

function draftFor(asset: SatelliteAssetInfo, live?: LiveSeed): BuildDraft {
  const factory = Array.from({ length: asset.slot_count }, (_, i) =>
    (i < asset.default_gpu_count ? asset.default_gpu : null))
  let slots = factory
  if (live?.slots?.length) {
    // Trim / pad to THIS platform's bay so a shorter stored list can't leave
    // the grid ragged.
    slots = Array.from({ length: asset.slot_count }, (_, i) => live.slots![i] ?? null)
  } else if (live?.config?.gpu && live.gpuCount) {
    const n = Math.min(live.gpuCount, asset.slot_count)
    slots = Array.from({ length: asset.slot_count }, (_, i) =>
      (i < n ? live.config!.gpu : null))
  }
  return {
    asset: asset.id,
    // Fall back to the platform's factory loadout — an audited design that
    // closes the power / thermal / eclipse checks, so a build only ever
    // starts from something that flies.
    config: { ...(live?.config ?? asset.config), gpu_slots: undefined },
    geometry: {
      solar_clusters_per_side: live?.geometry?.solar_clusters_per_side
        ?? asset.solar_clusters_per_side,
      radiator_long: live?.geometry?.radiator_long ?? asset.radiator_long,
      radiator_ratio: live?.geometry?.radiator_ratio ?? asset.radiator_ratio,
    },
    slots: slots.some(Boolean) ? slots : factory,
    workload_profile: live?.workload_profile ?? asset.workload_profile,
    // 'free' is the wheels-in-charge state, not a pointing choice — a build
    // commissions a satellite that holds an attitude.
    attitude_mode: (live?.attitude_mode && live.attitude_mode !== 'free')
      ? live.attitude_mode : 'sun',
  }
}

const toRequest = (d: BuildDraft): SatelliteBuildRequest => ({
  asset: d.asset,
  config: d.config,
  geometry: d.geometry,
  gpu_slots: d.slots,
  workload_profile: d.workload_profile,
  attitude_mode: d.attitude_mode,
})

/**
 * useSatelliteBuild — draft state for the Twin page's satellite builder plus
 * the debounced dry-run that keeps the physics verdict honest while editing.
 *
 * The dry-run (POST /satellite_build/preview) commissions the draft on a
 * DETACHED engine backend-side and returns the same derived stats and
 * per-schedule fit verdicts the live panels report — so "will this satellite
 * work?" is answered by the physics engine before Run, not by a client-side
 * approximation of it.
 */
export function useSatelliteBuild(assets: SatelliteAssetInfo[]) {
  const [draft, setDraft] = useState<BuildDraft | null>(null)
  const [preview, setPreview] = useState<SatelliteBuildPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const asset = useMemo(
    () => assets.find((a) => a.id === draft?.asset) ?? null,
    [assets, draft?.asset])

  const selectAsset = useCallback((a: SatelliteAssetInfo, live?: LiveSeed) => {
    // Switching platforms restarts the build: the bay size, the hull and the
    // deployables all belong to the platform, so carrying the old numbers
    // over would silently produce a satellite nobody specced. Re-picking the
    // platform already selected is a no-op (it would wipe your edits).
    setDraft((d) => (d?.asset === a.id ? d : draftFor(a, live)))
  }, [])

  const patchConfig = useCallback((patch: Partial<SatelliteConfig>) => {
    setDraft((d) => (d ? { ...d, config: { ...d.config, ...patch } } : d))
  }, [])

  const patchGeometry = useCallback((patch: Partial<BuildGeometry>) => {
    setDraft((d) => (d ? { ...d, geometry: { ...d.geometry, ...patch } } : d))
  }, [])

  const setSlot = useCallback((index: number, gpu: GpuType | null) => {
    setDraft((d) => {
      if (!d || index < 0 || index >= d.slots.length) return d
      const slots = [...d.slots]
      slots[index] = gpu
      return { ...d, slots }
    })
  }, [])

  const fillSlots = useCallback((gpu: GpuType | null) => {
    setDraft((d) => (d ? { ...d, slots: d.slots.map(() => gpu) } : d))
  }, [])

  const setWorkload = useCallback((id: string) => {
    setDraft((d) => (d ? { ...d, workload_profile: id } : d))
  }, [])

  const setAttitude = useCallback((mode: string) => {
    setDraft((d) => (d ? { ...d, attitude_mode: mode } : d))
  }, [])

  const fittedCount = draft?.slots.filter(Boolean).length ?? 0

  // --- Dry-run ------------------------------------------------------------
  // Debounced so dragging a stepper doesn't fire a request per click, and
  // sequenced so a slow early response can never overwrite a newer one.
  const runId = useRef(0)
  useEffect(() => {
    if (!draft) return
    const id = ++runId.current
    const t = setTimeout(async () => {
      // An empty bay has no physics to report and the backend would 422 it.
      if (draft.slots.every((s) => !s)) { setPreview(null); return }
      setPreviewing(true)
      try {
        const r = await fetch(`${BACKEND_HTTP}/satellite_build/preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(toRequest(draft)),
        })
        const body = r.ok ? ((await r.json()) as SatelliteBuildPreview) : null
        if (id === runId.current) setPreview(body)
      } catch {
        if (id === runId.current) setPreview(null)
      } finally {
        if (id === runId.current) setPreviewing(false)
      }
    }, 250)
    return () => clearTimeout(t)
  }, [draft])

  const submit = useCallback(async (): Promise<{ ok: boolean; regenerated: boolean }> => {
    if (!draft) return { ok: false, regenerated: false }
    setSubmitting(true)
    try {
      const r = await fetch(`${BACKEND_HTTP}/satellite_build`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(toRequest(draft)),
      })
      if (!r.ok) return { ok: false, regenerated: false }
      const body = (await r.json()) as { ok: boolean; regenerated: boolean }
      return { ok: body.ok === true, regenerated: body.regenerated === true }
    } catch {
      return { ok: false, regenerated: false }
    } finally {
      setSubmitting(false)
    }
  }, [draft])

  return {
    draft, asset, fittedCount, preview, previewing, submitting,
    selectAsset, patchConfig, patchGeometry, setSlot, fillSlots,
    setWorkload, setAttitude, submit,
  }
}
