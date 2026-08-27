import { Rocket } from 'lucide-react'
import { useSatelliteAssets } from '../../../hooks/useSatelliteAssets'
import { useBuilderStore } from '../../../store/useBuilderStore'

/**
 * BuilderChip — header entry point back into the satellite builder, showing
 * the platform the satellite currently flies on. Sits beside the Designs and
 * Compare chips: a design preset is someone else's finished satellite, a
 * build is yours.
 */
export function BuilderChip() {
  const openBuilder = useBuilderStore((s) => s.openBuilder)
  const { assets, activeId } = useSatelliteAssets()
  const active = assets.find((a) => a.id === activeId)

  return (
    <button
      type="button"
      data-testid="open-builder"
      onClick={openBuilder}
      className="flex items-center gap-1.5 rounded border border-border-weak bg-bg-inset/40 px-2 py-1
                 text-[11px] text-text-md hover:border-border-med hover:text-text-hi"
      title="Rebuild the satellite: platform, structure, payload slots, workload"
    >
      <Rocket size={12} strokeWidth={1.8} className="text-text-lo" />
      <span className="uppercase tracking-[0.10em]">Build</span>
      <span className="font-mono text-[10px] text-text-hi">{active?.vendor ?? '—'}</span>
    </button>
  )
}
