import { Check, Cpu, Layers, Sun, Thermometer } from 'lucide-react'
import { assetPreviewSrc } from '../../../hooks/useSatelliteAssets'
import type { SatelliteAssetInfo } from '../../../types/messages'
import { AdaArt, SophiaArt } from './assetArt'

/** Platforms drawn from the vendor's PUBLISHED reference design instead of
 *  rendered from a hull — see assetArt.tsx for why. */
const ASSET_ART: Record<string, (() => React.ReactElement) | undefined> = {
  sophia: SophiaArt,
  ada: AdaArt,
}

/**
 * Step 1 — pick the vendor PLATFORM. Each card is a genuinely different hull
 * (a different USD architecture, not a rescale) with its own payload-bay size
 * and the factory loadout it ships with; picking one seeds every later step.
 */
export function StepAsset({
  assets, selected, activeId, onPick,
}: {
  assets: SatelliteAssetInfo[]
  selected: string | null
  activeId: string | null
  onPick: (a: SatelliteAssetInfo) => void
}) {
  const picked = assets.find((a) => a.id === selected)
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] leading-relaxed text-text-lo">
        Choose the satellite platform to build on. The hull, the payload-bay slot count and
        the deployables all come from the platform; everything below is yours to configure.
      </p>
      <div className="grid grid-cols-4 gap-3">
        {assets.map((a) => (
          <AssetCard
            key={a.id}
            asset={a}
            selected={a.id === selected}
            flying={a.id === activeId}
            onPick={() => onPick(a)}
          />
        ))}
      </div>

      {picked && (
        <div className="rounded-md border border-border-weak bg-bg-inset/30 p-3">
          <div className="mb-1 flex items-baseline gap-2">
            <span className="text-[11px] font-medium text-text-hi">{picked.name}</span>
            <span className="text-[10px] uppercase tracking-[0.08em] text-text-lo">
              {picked.architecture} hull · {picked.slot_count} slots
            </span>
          </div>
          <p className="max-w-[70ch] text-[11px] leading-relaxed text-text-lo">
            {picked.description}
          </p>
          <p className="mt-2 text-[10px] text-text-faint">
            Ships as {picked.default_gpu_count}× {picked.default_gpu} on a
            {' '}{picked.config.solar_material} / {picked.config.radiator_material} loadout —
            a flight-checked starting point you can change in the next steps.
          </p>
        </div>
      )}
    </div>
  )
}

function AssetCard({
  asset: a, selected, flying, onPick,
}: {
  asset: SatelliteAssetInfo
  selected: boolean
  flying: boolean
  onPick: () => void
}) {
  const s = a.stats
  const Art = ASSET_ART[a.id]
  return (
    <button
      type="button"
      data-testid={`build-asset-${a.id}`}
      onClick={onPick}
      aria-pressed={selected}
      className={
        'group flex flex-col overflow-hidden rounded-md border text-left transition-colors ' +
        (selected
          ? 'border-accent bg-bg-card-hi'
          : 'border-border-weak bg-bg-inset/40 hover:border-border-glow hover:bg-bg-card-hi')
      }
    >
      {/* Square, because the rendered previews are square — the drawn
          platforms use the same box so every card's image area is identical.
          Platforms whose hull we actually have show a render of the model they
          will fly; the rest are drawn from the vendor's published reference
          design (assetArt.tsx) rather than showing a stand-in hull that looks
          nothing like the real satellite. */}
      <div className="relative aspect-square w-full bg-[#05070e]">
        {Art ? <Art /> : (
          <img
            src={assetPreviewSrc(a)}
            alt={`${a.name} preview`}
            loading="lazy"
            className="h-full w-full object-cover"
            onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
            onLoad={(e) => { (e.target as HTMLImageElement).style.visibility = '' }}
          />
        )}
        {selected && (
          <span className="absolute left-2 top-2 flex items-center gap-1 rounded bg-accent px-1.5 py-0.5
                           text-[9px] font-semibold uppercase tracking-[0.10em] text-black">
            <Check size={10} strokeWidth={2.5} /> Selected
          </span>
        )}
        {flying && !selected && (
          <span className="absolute left-2 top-2 rounded border border-border-med bg-black/60 px-1.5 py-0.5
                           text-[9px] uppercase tracking-[0.10em] text-text-md">
            In orbit
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1.5 p-2.5">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[12px] font-medium text-text-hi">{a.name}</span>
          <span className="shrink-0 text-[10px] uppercase tracking-[0.08em] text-text-lo">
            {a.vendor}
          </span>
        </div>
        {/* Exactly two lines tall whatever the tagline's length, so the stat
            grids below line up across the row. */}
        <span className="line-clamp-2 h-[2.75em] text-[10px] leading-snug text-text-lo">
          {a.tagline}
        </span>

        <div className="mt-0.5 grid grid-cols-2 gap-x-2 gap-y-1">
          <Stat icon={<Layers size={10} />}      label={`${a.slot_count} slots`}        value={`${a.default_gpu_count} fit`} />
          <Stat icon={<Cpu size={10} />}         label={a.default_gpu}                  value={`${s.compute_pflops.toFixed(0)} PF`} />
          <Stat icon={<Sun size={10} />}         label={`${s.solar_area_m2.toFixed(0)} m²`} value={`${(s.peak_solar_w / 1000).toFixed(1)} kW`} />
          <Stat icon={<Thermometer size={10} />} label={`${s.radiator_area_m2.toFixed(0)} m²`} value={`ε ${s.radiator_emissivity.toFixed(2)}`} />
        </div>
      </div>
    </button>
  )
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <span className="flex items-center gap-1 text-[10px] text-text-md">
      <span className="text-accent">{icon}</span>
      <span className="truncate font-mono tabular-nums">{label}</span>
      <span className="ml-auto shrink-0 font-mono tabular-nums text-text-lo">{value}</span>
    </span>
  )
}
