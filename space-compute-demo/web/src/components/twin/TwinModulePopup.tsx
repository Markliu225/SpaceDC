import { useEffect, useMemo } from 'react'
import { useDemoStore } from '../../store/demoStore'
import { PopupChrome } from './panels/PopupPrimitives'
import { ShellPanel } from './panels/ShellPanel'
import { RadarPanel } from './panels/RadarPanel'
import { GpuPanel } from './panels/GpuPanel'
import { SolarPanel } from './panels/SolarPanel'

/**
 * TwinModulePopup — dispatcher for the Satellite Twin viewport's click-to-
 * info popup. Reads selectedPrim from demoStore, matches it against the
 * three module kinds authored under /World/Satellite/Bus by the Tripo
 * satellite_body.usdz (payload bay shell, radar dish, and the row of GPU
 * modules), and renders the matching sub-panel anchored top-right of the
 * viewport.
 *
 * Selection flow recap:
 *   click prim in WebRTC stream
 *     → Kit's space.demo.selection extension catches USD SELECTION_CHANGED
 *     → POST /selection {prim_path} to backend
 *     → backend broadcasts `selection_changed` WS envelope
 *     → demoStore.selectedPrim updates
 *     → THIS component matches & renders the right sub-panel
 *
 * Close: × button OR Escape both call selectObject('') which round-trips
 * a clear through the same path, so every web client closes in lockstep.
 */

// Path-suffix anchored: the asset's /root/ParentNode is wrapped at runtime
// under /World/Satellite/Bus/<...>/, but every selection_changed path ends
// with .../tripo_part_<N>(/Mesh_<M>)?. Order matters — shell + radar are
// disjoint singletons, GPU is the row.
const MATCHERS: { kind: 'shell' | 'radar' | 'gpu' | 'solar'; re: RegExp }[] = [
  { kind: 'shell', re: /.*\/tripo_part_9(\/Mesh_\d+)?$/ },
  { kind: 'radar', re: /.*\/tripo_part_4(\/Mesh_\d+)?$/ },
  { kind: 'gpu',   re: /.*\/tripo_part_(1|11|12|13|14|15|16)(\/Mesh_\d+)?$/ },
  // Solar wings — clicking any descendant of PanelLeft/PanelRight (the
  // wrapper Xform, the referenced tripo_node, or its mesh) opens the wing
  // popup. Side captured in group 1.
  { kind: 'solar', re: /.*\/(PanelLeft|PanelRight)(?:\/.*)?$/ },
]

// The 7 GPU prims in the asset, listed by ascending source-X (the visible
// row order from left to right). Drives a stable "Module · NN" label so a
// user clicking the leftmost prim sees Module 01, not Module 13.
const GPU_PART_ORDER = [
  'tripo_part_13', // x ≈ -0.31
  'tripo_part_1',  // x ≈ -0.20
  'tripo_part_15', // x ≈ -0.10
  'tripo_part_12', // x ≈  0.00
  'tripo_part_14', // x ≈  0.11
  'tripo_part_16', // x ≈  0.22
  'tripo_part_11', // x ≈  0.32
] as const

interface Match {
  kind: 'shell' | 'radar' | 'gpu' | 'solar'
  partId: string
}

function matchSelection(path: string | null): Match | null {
  if (!path) return null
  for (const { kind, re } of MATCHERS) {
    const m = re.exec(path)
    if (!m) continue
    let partId: string
    if (kind === 'gpu')        partId = `tripo_part_${m[1]}`
    else if (kind === 'shell') partId = 'tripo_part_9'
    else if (kind === 'radar') partId = 'tripo_part_4'
    else                       partId = m[1]   // 'PanelLeft' | 'PanelRight'
    return { kind, partId }
  }
  return null
}

const HEADER = {
  shell: { title: 'Payload Bay',      subtitle: 'Shell · MLI / Radiator', swatch: '#B69755' },
  radar: { title: 'Maritime Payload', subtitle: 'X-band SAR · Comms',     swatch: '#3B9EFF' },
  gpu:   { title: 'GPU Compute',      subtitle: '',                       swatch: '#E8EEFB' },
  solar: { title: 'Solar Wing',       subtitle: 'PV array · radiator',    swatch: '#22D3EE' },
} as const

export function TwinModulePopup() {
  const selected  = useDemoStore((s) => s.selectedPrim)
  const selectObj = useDemoStore((s) => s.selectObject)
  const match     = useMemo(() => matchSelection(selected), [selected])

  useEffect(() => {
    if (!match) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') selectObj('')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [match?.kind, selectObj])

  if (!match) return null

  const close = () => selectObj('')
  const gpuIdx = match.kind === 'gpu'
    ? (GPU_PART_ORDER.indexOf(match.partId as typeof GPU_PART_ORDER[number]) + 1) || 1
    : 0

  const head = HEADER[match.kind]
  const subtitle =
    match.kind === 'gpu'   ? `Card ${String(gpuIdx).padStart(2, '0')} · live` :
    match.kind === 'solar' ? `${match.partId === 'PanelLeft' ? 'East' : 'West'} wing · live`
                           : head.subtitle

  return (
    <div className="pointer-events-none absolute right-3 top-3 z-40">
      <PopupChrome
        title={head.title}
        subtitle={subtitle}
        swatchColor={head.swatch}
        onClose={close}
      >
        {match.kind === 'shell' && <ShellPanel />}
        {match.kind === 'radar' && <RadarPanel />}
        {match.kind === 'gpu'   && <GpuPanel cardIdx={gpuIdx} />}
        {match.kind === 'solar' && <SolarPanel side={match.partId as 'PanelLeft' | 'PanelRight'} />}
      </PopupChrome>
    </div>
  )
}
