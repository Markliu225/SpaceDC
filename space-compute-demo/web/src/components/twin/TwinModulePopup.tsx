import { useEffect, useMemo } from 'react'
import { useDemoStore } from '../../store/demoStore'
import { PopupChrome } from './panels/PopupPrimitives'
import { GpuPanel } from './panels/GpuPanel'
import { SolarPanel } from './panels/SolarPanel'
import { RadiatorPanel } from './panels/RadiatorPanel'
import { StructurePanel, type StructureSub } from './panels/StructurePanel'

/**
 * TwinModulePopup — component-level click-to-info for the Satellite Twin
 * viewport. Reads selectedPrim from demoStore (set from Kit's selection
 * round-trip, or driven directly for tests) and matches it against the
 * current twin model authored by tools/gen_twin_satellite.py:
 *
 *   /World/Satellite/Servers/Server_<rack>_<i>      → server (GPU blade)
 *   /World/Satellite/SolarArray/Wing{Pos,Neg}Y/…    → solar wing
 *   /World/Satellite/RadiatorArray/Radiator{Top,Bot}→ radiator panel
 *   /World/Satellite/Backbone/…/tripo_part_<n>      → backbone structure
 *
 * Matching is by ANCESTOR keyword (not the exact leaf) so whichever sub-mesh
 * Kit reports as selected still resolves to the right component card.
 *
 * Close: × button OR Escape both call selectObject('') which round-trips a
 * clear through the same path, so every web client closes in lockstep.
 */

type Kind = 'server' | 'solar' | 'radiator' | 'structure'

interface Match {
  kind: Kind
  /** Header subtitle. */
  subtitle: string
  /** server: 1-based index · solar: 'Pos'|'Neg' · radiator: 'Top'|'Bot' ·
   *  structure: StructureSub */
  ref: string
}

// Rack order → contiguous 1..12 server numbering (left-to-right, top-to-bottom).
const RACK_ORDER: Record<string, number> = { UpY: 0, UnY: 1, LpY: 2, LnY: 3 }

// Backbone tripo_part_<n> → structural role.
function structureSub(part: string): StructureSub {
  if (part === '1') return 'spine'
  if (part === '2' || part === '8') return 'thruster'
  if (part === '6' || part === '7') return 'tank'
  if (part === '0' || part === '3' || part === '4' || part === '5') return 'rack'
  return 'antenna' // new_0 / new_1 + any other
}

function matchSelection(path: string | null): Match | null {
  if (!path) return null

  let m = /\/Servers\/Server_([A-Za-z]+)_(\d+)/.exec(path)
  if (m) {
    const rack = m[1]
    const idx = Number(m[2])
    const num = (RACK_ORDER[rack] ?? 0) * 3 + idx + 1
    return { kind: 'server', subtitle: `Blade ${String(num).padStart(2, '0')} · live`, ref: String(num) }
  }

  m = /\/SolarArray\/Wing(Pos|Neg)Y/.exec(path)
  if (m) return { kind: 'solar', subtitle: `${m[1] === 'Pos' ? '+Y' : '−Y'} wing · live`, ref: m[1] }

  m = /\/RadiatorArray\/(?:Radiator|RadBoom)(Top|Bot)/.exec(path)
  if (m) return { kind: 'radiator', subtitle: `${m[1] === 'Top' ? '+Z' : '−Z'} panel · live`, ref: m[1] }

  m = /\/Backbone\/.*tripo_part_(new_\d+|\d+)/.exec(path)
  if (m) {
    const sub = structureSub(m[1])
    return { kind: 'structure', subtitle: 'Platform · backbone', ref: sub }
  }
  if (path.includes('/Backbone')) {
    return { kind: 'structure', subtitle: 'Platform · backbone', ref: 'spine' }
  }
  return null
}

const HEADER: Record<Kind, { title: string; swatch: string }> = {
  server:    { title: 'Compute Server',  swatch: '#E8EEFB' },
  solar:     { title: 'Solar Wing',      swatch: '#22D3EE' },
  radiator:  { title: 'Radiator',        swatch: '#F59E0B' },
  structure: { title: 'Structure',       swatch: '#B69755' },
}

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
  const head = HEADER[match.kind]

  return (
    <div className="pointer-events-none absolute right-3 top-3 z-40">
      <PopupChrome
        title={head.title}
        subtitle={match.subtitle}
        swatchColor={head.swatch}
        onClose={close}
      >
        {match.kind === 'server'    && <GpuPanel cardIdx={Number(match.ref)} />}
        {match.kind === 'solar'     && <SolarPanel wing={match.ref as 'Pos' | 'Neg'} />}
        {match.kind === 'radiator'  && <RadiatorPanel which={match.ref as 'Top' | 'Bot'} />}
        {match.kind === 'structure' && <StructurePanel sub={match.ref as StructureSub} />}
      </PopupChrome>
    </div>
  )
}
