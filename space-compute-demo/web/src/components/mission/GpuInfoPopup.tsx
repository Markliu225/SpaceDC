import { useEffect } from 'react'
import { useDemoStore } from '../../store/demoStore'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { gpuOption, GPU_CARDS_PER_SAT } from '../../data/satConfigOptions'

/**
 * GpuInfoPopup — small floating card that appears in the top-right of the
 * Mission viewport when the user clicks a GPU card in the WebRTC Omniverse
 * stream. The data flow is:
 *
 *   click prim in stream
 *     → Kit's space.demo.selection extension catches USD SELECTION_CHANGED
 *     → POST /selection { prim_path } to backend
 *     → backend broadcasts `selection_changed` WS envelope to every client
 *     → demoStore.selectedPrim is updated
 *     → this component reads it and renders if the path matches a GPU card
 *
 * Closes when the user clicks anywhere on the page or hits Escape. Re-opens
 * when a (possibly different) GPU card is clicked again.
 */

const GPU_CARD_PATH_RE = /^\/World\/ComputeCore\/Card_(\d+)$/

export function GpuInfoPopup() {
  const selected   = useDemoStore((s) => s.selectedPrim)
  const selectObj  = useDemoStore((s) => s.selectObject)
  const satConfig  = useTelemetryStore((s) => s.satConfig)

  const match = selected ? GPU_CARD_PATH_RE.exec(selected) : null

  useEffect(() => {
    if (!match) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') selectObj('')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [match, selectObj])

  if (!match) return null

  const cardIdx = parseInt(match[1], 10)
  const gpu = gpuOption(satConfig.gpu)
  const perSatPflops = gpu.pflops_per_card * GPU_CARDS_PER_SAT
  const perSatTdpKw  = (gpu.tdp_w * GPU_CARDS_PER_SAT) / 1000
  const perSatCostK  = gpu.cost_k * GPU_CARDS_PER_SAT

  return (
    <div
      className="pointer-events-none absolute right-3 top-3 z-40"
      role="dialog" aria-label={`GPU card ${cardIdx} details`}
    >
      <div className="pointer-events-auto w-[228px] rounded border border-border-med bg-card shadow-card">
        {/* Header — card id + GPU model + close. */}
        <div className="flex items-center justify-between border-b border-border-weak px-3 py-2">
          <div className="flex items-center gap-2">
            <span
              className="h-3 w-3 rounded-sm ring-1 ring-white/10"
              style={{ background: gpu.tint }}
              aria-hidden
            />
            <div className="flex flex-col leading-tight">
              <span className="text-[10px] uppercase tracking-[0.14em] text-text-md">
                GPU Card · {String(cardIdx).padStart(2, '0')}
              </span>
              <span className="text-[11px] uppercase tracking-[0.06em] text-accent font-mono">
                {gpu.label}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => selectObj('')}
            aria-label="Close"
            className="flex h-5 w-5 items-center justify-center rounded text-text-lo hover:text-text-hi hover:bg-bg-cardHi"
          >
            <span className="text-[13px] leading-none">×</span>
          </button>
        </div>

        {/* Per-card stats. */}
        <Section title="Per card">
          <Row label="Compute" value={gpu.pflops_per_card.toFixed(2)} unit="PF" />
          <Row label="TDP"     value={String(gpu.tdp_w)}             unit="W" />
          <Row label="BOM"     value={String(gpu.cost_k)}            unit="$K" />
        </Section>

        {/* Per-sat aggregate ({GPU_CARDS_PER_SAT}× cards). */}
        <Section title={`Per satellite · ${GPU_CARDS_PER_SAT}×`}>
          <Row label="Compute" value={perSatPflops.toFixed(2)}           unit="PF" />
          <Row label="TDP"     value={perSatTdpKw.toFixed(1)}            unit="KW" />
          <Row label="BOM"     value={perSatCostK.toLocaleString()}      unit="$K" />
        </Section>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-border-weak px-3 py-2 last:border-b-0">
      <div className="mb-1 text-[9.5px] uppercase tracking-[0.14em] text-text-lo">{title}</div>
      <div className="flex flex-col gap-[3px]">{children}</div>
    </div>
  )
}

function Row({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="flex items-baseline justify-between text-[11px]">
      <span className="text-text-md">{label}</span>
      <span className="font-mono tabular-nums text-text-hi">
        {value}
        {unit ? <span className="ml-1 text-[9.5px] text-text-lo">{unit}</span> : null}
      </span>
    </div>
  )
}
