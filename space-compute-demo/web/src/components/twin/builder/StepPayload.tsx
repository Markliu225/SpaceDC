import { Cpu, Eraser } from 'lucide-react'
import { GPU_OPTIONS, GPU_SLOT_TINT, gpuOption, slotGroups } from '../../../data/satConfigOptions'
import type { GpuType, SatelliteAssetInfo } from '../../../types/messages'

/**
 * Step 3 — PAYLOAD DESIGN: which accelerator goes in which slot.
 *
 * The bay is painted, not form-filled: pick a card (or Empty) as the brush,
 * then click slots. Twelve dropdowns would be twelve interactions to fit a
 * rack; this is one. The grid order matches the 3D model's slot order, so
 * slot 5 here is the blade that lights up in the viewport — and empty slots
 * really do render empty after Run.
 *
 * A bay may hold more than one card model. The engine then treats each model
 * as its own tensor-parallel group and sums them, so mixing is a real (if
 * unusual) design choice rather than a UI-only nicety.
 */
export function StepPayload({
  asset, slots, onSlot, onFill, brush, onBrush,
}: {
  asset: SatelliteAssetInfo
  slots: (GpuType | null)[]
  onSlot: (index: number, gpu: GpuType | null) => void
  onFill: (gpu: GpuType | null) => void
  brush: GpuType | null
  onBrush: (gpu: GpuType | null) => void
}) {
  const groups = slotGroups(slots)
  const fitted = slots.filter(Boolean).length
  const peakW = groups.reduce((w, g) => w + gpuOption(g.gpu).tdp_w * g.count, 0)
  const pflops = groups.reduce((p, g) => p + gpuOption(g.gpu).pflops_per_card * g.count, 0)
  const capexK = groups.reduce((c, g) => c + gpuOption(g.gpu).cost_k * g.count, 0)

  // Slots are laid out in the platform's own grouping (racks, bay rows, tile
  // columns) so the grid reads like the hardware.
  const groupSize = Math.max(1, asset.slot_group_size)
  const rows: number[][] = []
  for (let i = 0; i < slots.length; i += groupSize) {
    rows.push(Array.from({ length: Math.min(groupSize, slots.length - i) }, (_, k) => i + k))
  }

  const chip = 'flex items-center gap-2 rounded border px-3 py-2 text-[13px]'
  const chipOn = 'border-accent bg-accent/15 text-text-hi'
  const chipOff = 'border-border-weak bg-bg-inset/40 text-text-md hover:bg-bg-card-hi hover:text-text-hi'

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <p className="text-[13px] leading-relaxed text-text-lo">
        <span className="text-text-hi">Satellite payload design</span> — fit the {asset.slot_count}
        {' '}payload slots of the {asset.name}. Pick a card below, then click slots to place it;
        leave a slot empty to fly lighter and cooler.
      </p>

      {/* Brush palette. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-[12px] uppercase tracking-[0.10em] text-text-lo">Card</span>
        {GPU_OPTIONS.map((o) => (
          <button
            key={o.id}
            type="button"
            data-testid={`build-brush-${o.id}`}
            onClick={() => onBrush(o.id)}
            aria-pressed={brush === o.id}
            className={`${chip} ${brush === o.id ? chipOn : chipOff}`}
          >
            <span className="h-3 w-3 rounded-sm" style={{ background: GPU_SLOT_TINT[o.id] }} />
            {o.id}
            <span className="font-mono tabular-nums text-[12px] text-text-lo">
              {o.pflops_per_card.toFixed(2)} PF · {o.tdp_w} W
            </span>
          </button>
        ))}
        <button
          type="button"
          data-testid="build-brush-empty"
          onClick={() => onBrush(null)}
          aria-pressed={brush === null}
          className={`${chip} ${brush === null ? chipOn : chipOff}`}
        >
          <Eraser size={13} strokeWidth={1.8} /> Empty
        </button>
        <span className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => onFill(brush)}
            className="rounded border border-border-weak px-3 py-2 text-[12px] uppercase tracking-[0.08em]
                       text-text-md hover:bg-bg-card-hi hover:text-text-hi"
          >
            Fill all
          </button>
          <button
            type="button"
            onClick={() => onFill(null)}
            className="rounded border border-border-weak px-3 py-2 text-[12px] uppercase tracking-[0.08em]
                       text-text-md hover:bg-bg-card-hi hover:text-text-hi"
          >
            Clear
          </button>
        </span>
      </div>

      {/* The bay — centred in whatever height is left. */}
      <div data-testid="build-slot-grid"
           className="flex min-h-0 flex-1 flex-col justify-center gap-4 overflow-y-auto rounded-md
                      border border-border-weak bg-bg-inset/20 p-5">
        {rows.map((row, r) => (
          <div key={r} className="mx-auto flex w-fit items-center gap-4">
            <span className="w-24 shrink-0 text-right text-[12px] uppercase tracking-[0.08em] text-text-faint">
              {rows.length > 1 ? `${asset.slot_group_label} ${r + 1}` : asset.slot_group_label}
            </span>
            <div className="flex flex-1 flex-wrap gap-3">
              {row.map((i) => (
                <Slot
                  key={i}
                  index={i}
                  label={asset.slot_labels[i] ?? `S${i + 1}`}
                  gpu={slots[i] ?? null}
                  onClick={() => onSlot(i, brush)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* What the bay adds up to — the sanity check before the workload step. */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5 rounded border border-border-weak
                      bg-bg-inset/40 px-3.5 py-2.5 text-[12px]">
        <Tally k="Fitted" v={`${fitted} / ${asset.slot_count}`} tone={fitted ? '' : 'text-err'} />
        <Tally k="Loadout" v={groups.length ? groups.map((g) => `${g.count}×${g.gpu}`).join(' + ') : 'empty'} />
        <Tally k="Peak compute" v={`${pflops.toFixed(1)} PF`} />
        <Tally k="Peak payload" v={`${(peakW / 1000).toFixed(2)} kW`} />
        <Tally k="Card CAPEX" v={`$${(capexK / 1000).toFixed(2)}M`} />
        {groups.length > 1 && (
          <span className="text-text-faint">
            Mixed bay — each card model runs as its own tensor-parallel group.
          </span>
        )}
      </div>
    </div>
  )
}

function Slot({
  index, label, gpu, onClick,
}: { index: number; label: string; gpu: GpuType | null; onClick: () => void }) {
  const tint = gpu ? GPU_SLOT_TINT[gpu] : null
  return (
    <button
      type="button"
      data-testid={`build-slot-${index}`}
      onClick={onClick}
      title={`Slot ${label}${gpu ? ` — ${gpu}` : ' — empty'}`}
      className={`flex w-[124px] flex-col gap-1.5 rounded-md border px-2.5 py-2.5 text-left transition-colors ${
        gpu
          ? 'border-border-med bg-bg-card-hi hover:border-border-glow'
          : 'border-dashed border-border-weak bg-bg-inset/30 hover:border-border-med'
      }`}
    >
      <span className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-[0.08em] text-text-faint">{label}</span>
        {gpu
          ? <Cpu size={13} strokeWidth={1.8} style={{ color: tint ?? undefined }} />
          : <span className="text-[11px] text-text-faint">—</span>}
      </span>
      <span className={`truncate font-mono text-[14px] ${gpu ? 'text-text-hi' : 'text-text-faint'}`}>
        {gpu ?? 'empty'}
      </span>
      <span className="h-[4px] w-full rounded-sm"
            style={{ background: tint ?? 'rgba(255,255,255,0.06)' }} />
    </button>
  )
}

function Tally({ k, v, tone = '' }: { k: string; v: string; tone?: string }) {
  return (
    <span className="flex items-baseline gap-2">
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className={`font-mono text-[13px] tabular-nums ${tone || 'text-text-hi'}`}>{v}</span>
    </span>
  )
}
