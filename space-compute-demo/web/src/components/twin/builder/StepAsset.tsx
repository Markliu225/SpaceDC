import { Check, Cpu, Layers, Sun } from 'lucide-react'
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
    <div className="flex h-full min-h-0 flex-col gap-4">
      <p className="text-[13px] leading-relaxed text-text-lo">
        Choose the satellite platform to build on. The hull, the payload-bay slot count and
        the deployables all come from the platform; everything after this is yours to configure.
      </p>
      <div className="grid grid-cols-4 gap-4">
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

      {/* The selected platform in full — grows into whatever height is left so
          the step reads as a filled page rather than a strip of cards. */}
      {picked && (
        <div className="grid min-h-0 flex-1 grid-cols-[1.4fr_1fr] gap-4 rounded-md border
                        border-border-weak bg-bg-inset/30 p-4">
          <div className="flex min-w-0 flex-col gap-2.5">
            <div className="flex items-baseline gap-2.5">
              <span className="text-[16px] font-medium text-text-hi">{picked.name}</span>
              <span className="text-[12px] uppercase tracking-[0.08em] text-text-lo">
                {picked.vendor}
              </span>
            </div>
            <p className="max-w-[72ch] text-[13px] leading-relaxed text-text-md">
              {picked.description}
            </p>
            <p className="mt-auto text-[12px] leading-relaxed text-text-lo">
              Ships as {picked.default_gpu_count}× {picked.default_gpu} on a
              {' '}{picked.config.solar_material} / {picked.config.radiator_material} loadout —
              a flight-checked starting point you can change in the next steps.
            </p>
          </div>

          <div className="flex flex-col gap-2.5 rounded border border-border-weak bg-bg-card-hi/50 p-3.5">
            <span className="text-[12px] uppercase tracking-[0.12em] text-text-md">
              Factory loadout
            </span>
            {/* Two columns: eight stacked rows overflow the panel at this
                type size. */}
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 overflow-y-auto">
              <Spec k="Hull" v={picked.architecture} />
              <Spec k="Slots" v={`${picked.slot_count} · ${picked.default_gpu_count} fitted`} />
              <Spec k="Cards" v={`${picked.default_gpu_count} × ${picked.default_gpu}`} />
              <Spec k="Compute" v={`${picked.stats.compute_pflops.toFixed(1)} PF`} />
              <Spec k="Solar" v={`${picked.stats.solar_area_m2} m²`} />
              <Spec k="Peak gen" v={`${(picked.stats.peak_solar_w / 1000).toFixed(1)} kW`} />
              <Spec k="Radiator" v={`${picked.stats.radiator_area_m2} m²`} />
              <Spec k="Emissivity" v={`ε ${picked.stats.radiator_emissivity.toFixed(2)}`} />
              <Spec k="Battery" v={`${(picked.battery_capacity_wh / 1000).toFixed(1)} kWh`} />
              <Spec k="Platform" v={`${picked.platform_power_w} W`} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Spec({ k, v }: { k: string; v: string }) {
  return (
    <span className="flex items-baseline justify-between gap-3 text-[12px]">
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className="truncate font-mono tabular-nums text-text-hi">{v}</span>
    </span>
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
          <span className="absolute left-2.5 top-2.5 flex items-center gap-1 rounded bg-accent px-2 py-1
                           text-[11px] font-semibold uppercase tracking-[0.10em] text-black">
            <Check size={12} strokeWidth={2.5} /> Selected
          </span>
        )}
        {flying && !selected && (
          <span className="absolute left-2.5 top-2.5 rounded border border-border-med bg-black/60 px-2 py-1
                           text-[11px] uppercase tracking-[0.10em] text-text-md">
            In orbit
          </span>
        )}
      </div>

      <div className="flex flex-col gap-2 p-3">
        {/* The vendor is the first word of every platform name, so a separate
            vendor tag here only stole width from the name. */}
        <span className="truncate text-[15px] font-medium text-text-hi">{a.name}</span>
        {/* Exactly two lines tall whatever the tagline's length, so the stat
            rows below line up across the row of cards. */}
        <span className="line-clamp-2 h-[2.75em] text-[12px] leading-snug text-text-lo">
          {a.tagline}
        </span>

        {/* Full-width rows: at four cards across there is no room for a
            two-column grid without truncating every label. */}
        <div className="mt-0.5 flex flex-col gap-1.5">
          <Stat icon={<Layers size={13} />}
                label="Bay" value={`${a.slot_count} slots · ${a.default_gpu_count} fitted`} />
          <Stat icon={<Cpu size={13} />}
                label="Compute" value={`${a.default_gpu} · ${s.compute_pflops.toFixed(0)} PF`} />
          <Stat icon={<Sun size={13} />}
                label="Solar" value={`${s.solar_area_m2.toFixed(0)} m² · ${(s.peak_solar_w / 1000).toFixed(1)} kW`} />
        </div>
      </div>
    </button>
  )
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <span className="flex items-center gap-2 text-[12px] text-text-md">
      <span className="shrink-0 text-accent">{icon}</span>
      <span className="shrink-0 uppercase tracking-[0.06em] text-text-lo">{label}</span>
      <span className="ml-auto truncate font-mono tabular-nums text-text-hi">{value}</span>
    </span>
  )
}
