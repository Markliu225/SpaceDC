import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, Cpu, Layers, Loader2, Scaling, Sun, Thermometer, X } from 'lucide-react'
import { useDesigns, previewSrc } from '../../hooks/useDesigns'
import type { DesignPresetInfo } from '../../types/messages'

/**
 * DesignGallery — header-strip entry point to the satellite design library.
 * The trigger chip shows the active design; the modal lists every preset with
 * its software-rendered USD thumbnail + derived stats. Clicking a card POSTs
 * /designs/{id}/apply: the backend swaps hardware config + deployable
 * geometry + workload profile in one shot, regenerates the USD (Kit reloads
 * the layer on the version bump) and broadcasts, so the viewport, the
 * Configurator and every telemetry panel move to the new design together.
 */
export function DesignGallery() {
  const { designs, activeId, offline, applying, applyDesign, refresh } = useDesigns()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const activeDesign = designs.find((d) => d.id === activeId)
  const activeLabel =
    activeId === 'custom' ? 'Custom' : activeDesign?.name ?? '—'

  // While an apply is in flight the modal refuses to close (the switch takes
  // a few seconds of USD regen; closing mid-flight would let the resolved
  // promise close/error a *reopened* modal).
  const close = useCallback(() => {
    if (applying) return
    setOpen(false); setError(null)
  }, [applying])

  const onPick = useCallback(async (d: DesignPresetInfo) => {
    if (applying || d.id === activeId) return
    setError(null)
    const res = await applyDesign(d.id)
    if (res.ok && res.regenerated) {
      setOpen(false); setError(null)
    } else if (res.ok) {
      setError(`Switched to “${d.name}”, but the 3D model failed to regenerate — ` +
               'the viewport may still show the old geometry (see backend log).')
    } else {
      setError(`Switch to “${d.name}” failed — backend offline or regen error.`)
    }
  }, [applying, activeId, applyDesign])

  // Load the list at mount (fills the trigger chip's active-design name) and
  // again on every open so a backend restart mid-session can't leave the
  // modal empty.
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  // Capture phase + stopPropagation so Escape closes ONLY the gallery —
  // TwinModulePopup's bubble-phase window listener (which would also clear
  // the viewport selection over WS) must not see the same keypress.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); close() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, close])

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded border border-border-weak bg-bg-inset/40 px-2 py-1
                   text-[11px] text-text-md hover:border-border-med hover:text-text-hi"
        title="Open the satellite design library"
      >
        <Layers size={12} strokeWidth={1.8} className="text-accent" />
        <span className="uppercase tracking-[0.10em]">Designs</span>
        <span className="font-mono text-[10px] text-text-hi">{activeLabel}</span>
      </button>

      {open && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 font-sans"
          onMouseDown={(e) => { if (e.target === e.currentTarget) close() }}
          role="dialog"
          aria-modal="true"
          aria-label="Satellite design library"
        >
          <div className="w-[900px] max-w-[94vw] max-h-[88vh] overflow-y-auto rounded-lg border
                          border-border-med bg-bg-card p-4 shadow-2xl">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Layers size={14} strokeWidth={1.8} className="text-accent" />
                <span className="text-[12px] uppercase tracking-[0.10em] text-text-hi">
                  Design Library
                </span>
              </div>
              <button
                type="button"
                onClick={close}
                className="rounded p-1 text-text-md hover:bg-bg-card-hi hover:text-text-hi"
                aria-label="close design library"
              >
                <X size={14} strokeWidth={1.8} />
              </button>
            </div>

            <p className="mb-3 text-[11px] leading-relaxed text-text-lo">
              Pick a design to switch the whole satellite: the 3D model regenerates and reloads
              in the viewport, and the power / thermal physics, hardware loadout and GPU workload
              schedule all follow.
            </p>

            {offline && (
              <div className="mb-3 rounded border border-warn/40 bg-warn/10 px-3 py-2 text-[11px] text-warn">
                Backend offline — start the FastAPI server (port 8001) to browse and switch designs.
              </div>
            )}
            {error && (
              <div className="mb-3 rounded border border-err/40 bg-err/10 px-3 py-2 text-[11px] text-err">
                {error}
              </div>
            )}

            <div className="grid grid-cols-3 gap-3">
              {designs.map((d) => (
                <DesignCard
                  key={d.id}
                  design={d}
                  active={d.id === activeId}
                  applying={applying === d.id}
                  disabled={applying !== null}
                  onPick={() => void onPick(d)}
                />
              ))}
            </div>

            {activeId === 'custom' && (
              <p className="mt-3 text-[10px] text-text-faint">
                Current loadout is a hand-edited <span className="font-mono">custom</span> design —
                applying a preset will replace it.
              </p>
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

function DesignCard({
  design: d, active, applying, disabled, onPick,
}: {
  design: DesignPresetInfo
  active: boolean
  applying: boolean
  disabled: boolean
  onPick: () => void
}) {
  const s = d.stats
  return (
    <button
      type="button"
      onClick={onPick}
      // The active card stays focusable (disabled would drop it from the tab
      // order) — onPick no-ops on it; aria-current carries the semantics.
      disabled={disabled && !active}
      aria-current={active ? 'true' : undefined}
      className={
        'group relative flex flex-col overflow-hidden rounded-md border text-left transition-colors ' +
        (active
          ? 'border-accent bg-bg-card-hi cursor-default'
          : 'border-border-weak bg-bg-inset/40 hover:border-border-glow hover:bg-bg-card-hi') +
        (disabled && !active ? ' opacity-60' : '')
      }
    >
      <div className="relative aspect-square w-full bg-[#05070e]">
        <img
          src={previewSrc(d)}
          alt={`${d.name} preview`}
          loading="lazy"
          className="h-full w-full object-cover"
          onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
          onLoad={(e) => { (e.target as HTMLImageElement).style.visibility = '' }}
        />
        {active && (
          <span className="absolute left-2 top-2 flex items-center gap-1 rounded bg-accent px-1.5 py-0.5
                           text-[9px] font-semibold uppercase tracking-[0.10em] text-black">
            <Check size={10} strokeWidth={2.5} /> Active
          </span>
        )}
        {applying && (
          <span className="absolute inset-0 flex items-center justify-center gap-2 bg-black/60
                           text-[11px] text-text-hi">
            <Loader2 size={14} className="animate-spin" /> Switching…
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1.5 p-2.5">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[12px] font-medium text-text-hi">{d.name}</span>
          <span className="text-[10px] uppercase tracking-[0.08em] text-text-lo">{d.config.gpu}</span>
        </div>
        <span className="line-clamp-2 min-h-[2em] text-[10px] leading-snug text-text-lo">
          {d.tagline}
        </span>

        <div className="mt-0.5 grid grid-cols-2 gap-x-2 gap-y-1">
          <Stat icon={<Cpu size={10} />}         label={`${d.config.gpu} ×${d.gpu_count}`} value={`${s.compute_pflops.toFixed(0)} PF`} />
          <Stat icon={<Sun size={10} />}         label={`${s.solar_area_m2.toFixed(0)} m²`} value={`${(s.peak_solar_w / 1000).toFixed(1)} kW`} />
          <Stat icon={<Thermometer size={10} />} label={`${s.radiator_area_m2.toFixed(0)} m²`} value={`ε ${s.radiator_emissivity.toFixed(2)}`} />
          <Stat icon={<Scaling size={10} />}     label={`${s.mass_kg} kg`}               value={`${(s.workload_avg_util * 100).toFixed(0)}% load`} />
        </div>

        <span className="mt-0.5 truncate text-[9px] uppercase tracking-[0.08em] text-text-faint">
          {s.workload_label}
        </span>
      </div>
    </button>
  )
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <span className="flex items-center gap-1 text-[10px] text-text-md">
      <span className="text-accent">{icon}</span>
      <span className="font-mono tabular-nums">{label}</span>
      <span className="ml-auto font-mono tabular-nums text-text-lo">{value}</span>
    </span>
  )
}
