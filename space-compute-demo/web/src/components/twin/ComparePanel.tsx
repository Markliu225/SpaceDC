import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { GitCompare, Loader2, Play, Square, X } from 'lucide-react'
import { useCompare } from '../../hooks/useCompare'
import type { CompareChoice, CompareDimension } from '../../types/messages'
import { COMPARE_PALETTE } from './comparePalette'

/**
 * ComparePanel — header-strip "Compare" entry on the Twin page.
 *
 * Pick a dimension (any Configurator knob, or whole designs) and 2–4
 * candidate values, then START: the backend seeds one offline engine per
 * variant from the live satellite's current state (same orbit phase, same
 * SOC / structure temperature) and steps them in LOCKSTEP with every 1 Hz
 * physics tick. The variants' curves grow and diverge IN REAL TIME as
 * dashed overlays on the Live Telemetry strip below the viewport — watch a
 * bare-aluminium radiator climb toward GPU throttle while OSR stays cool.
 * The live satellite and the 3D model are never touched; STOP ends it.
 */

const MAX_PICK = 4

export function ComparePanel() {
  const { options, compareLive, busy, offline, error, loadOptions, start, stop } = useCompare()
  const [open, setOpen] = useState(false)
  const [dimId, setDimId] = useState<string>('radiator_material')
  const [picked, setPicked] = useState<(string | number)[]>([])

  const dim = options?.dimensions.find((d) => d.id === dimId) ?? null
  const active = compareLive?.active === true

  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (open) void loadOptions()
  }, [open, loadOptions])

  // Selecting a dimension starts a fresh pick anchored on the live value —
  // "current vs …" is almost always the question being asked. Seed ONLY
  // when a chip actually exists for the live value (the backend prepends a
  // "Current · …" choice for off-list values, but e.g. the design dimension
  // has no chip while the live design is "custom" — seeding it would create
  // an invisible, un-deselectable pick). Seeding the CHIP's id (not
  // d.current) also survives numeric round-trip drift.
  const seedFor = (d: CompareDimension): (string | number)[] => {
    const cur = d.values.find((c) => String(c.id) === String(d.current))
    return cur ? [cur.id] : []
  }

  const selectDim = useCallback((d: CompareDimension) => {
    setDimId(d.id)
    setPicked(seedFor(d))
  }, [])

  // First options load: seed the pick for the initial dimension.
  useEffect(() => {
    if (options && picked.length === 0) {
      const d = options.dimensions.find((x) => x.id === dimId)
      if (d) setPicked(seedFor(d))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options])

  const toggleValue = useCallback((v: string | number) => {
    setPicked((prev) => {
      if (prev.includes(v)) return prev.filter((x) => x !== v)
      if (prev.length >= MAX_PICK) return prev
      return [...prev, v]
    })
  }, [])

  const onStart = useCallback(async () => {
    if (!dim || picked.length < 2) return
    const ok = await start(dim.id, picked)
    // Close on success so the user's eyes land on the telemetry strip,
    // where the comparison actually plays out.
    if (ok) setOpen(false)
  }, [dim, picked, start])

  // Escape closes only this modal (capture phase — see DesignGallery).
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
        data-testid="compare-open"
        onClick={() => setOpen(true)}
        className={
          'flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] ' +
          (active
            ? 'border-accent bg-accent/15 text-text-hi'
            : 'border-border-weak bg-bg-inset/40 text-text-md hover:border-border-med hover:text-text-hi')
        }
        title="Compare design options live — variant curves evolve on the telemetry strip"
      >
        <GitCompare size={12} strokeWidth={1.8} className="text-accent" />
        <span className="uppercase tracking-[0.10em]">Compare</span>
        {active && (
          <span className="font-mono text-[10px] text-accent">
            LIVE +{Math.round(compareLive?.elapsed_s ?? 0)}s
          </span>
        )}
      </button>

      {open && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-bg-app/70 font-sans"
          onMouseDown={(e) => { if (e.target === e.currentTarget) close() }}
          role="dialog"
          aria-modal="true"
          aria-label="What-if comparison"
        >
          <div className="w-[720px] max-w-[94vw] max-h-[90vh] overflow-y-auto rounded-lg border
                          border-border-med bg-bg-card p-4 shadow-modal">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitCompare size={14} strokeWidth={1.8} className="text-accent" />
                <span className="text-[12px] uppercase tracking-[0.10em] text-text-hi">
                  Live What-if Comparison
                </span>
              </div>
              <button
                type="button"
                onClick={close}
                className="rounded p-1 text-text-md hover:bg-bg-card-hi hover:text-text-hi"
                aria-label="close comparison"
              >
                <X size={14} strokeWidth={1.8} />
              </button>
            </div>

            <p className="mb-3 text-[11px] leading-relaxed text-text-lo">
              Pick a dimension and 2–{MAX_PICK} candidate values, then start. Each variant flies
              the same physics as the live satellite from this very moment — same orbit, same
              battery, same temperature — and its curve grows on the Live Telemetry strip in
              real time, so you watch the choices diverge as the simulation advances. The live
              satellite is not affected.
            </p>

            {offline && (
              <div className="mb-3 rounded border border-warn/40 bg-warn/10 px-3 py-2 text-[11px] text-warn">
                Backend offline — start the FastAPI server (port 8001) to run comparisons.
              </div>
            )}
            {error && !offline && (
              <div className="mb-3 rounded border border-err/40 bg-err/10 px-3 py-2 text-[11px] text-err">
                {error}
              </div>
            )}

            {/* Running-comparison status — live numbers at 1 Hz. */}
            {active && compareLive && (
              <div className="mb-3 rounded border border-accent/40 bg-accent/10 px-3 py-2"
                   data-testid="compare-status">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-[11px] uppercase tracking-[0.08em] text-accent">
                    Running · {compareLive.dimension_label} · +{Math.round(compareLive.elapsed_s)}s
                  </span>
                  <button
                    type="button"
                    data-testid="compare-stop"
                    onClick={() => void stop()}
                    disabled={busy}
                    className="flex items-center gap-1.5 rounded border border-err/50 bg-err/15 px-2 py-1
                               text-[10px] font-semibold uppercase tracking-[0.08em] text-err
                               hover:bg-err/25 disabled:opacity-40"
                  >
                    <Square size={10} strokeWidth={2.5} /> Stop
                  </button>
                </div>
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="text-left uppercase tracking-[0.08em] text-text-lo">
                      <th className="pb-0.5 font-normal">Variant</th>
                      <th className="pb-0.5 font-normal">Temp</th>
                      <th className="pb-0.5 font-normal">SOC</th>
                      <th className="pb-0.5 font-normal">Payload</th>
                      <th className="pb-0.5 font-normal">tok/s</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compareLive.variants.map((v, i) => (
                      <tr key={String(v.value)} className="text-text-md">
                        <td className="py-0.5">
                          <span className="flex items-center gap-1.5">
                            <span className="inline-block h-[3px] w-3.5 rounded-full"
                                  style={{ background: COMPARE_PALETTE[i] }} />
                            <span className="max-w-[200px] truncate text-text-hi">{v.label}</span>
                          </span>
                        </td>
                        <td className="py-0.5 tabular">{v.temperature_c.toFixed(1)} °C</td>
                        <td className="py-0.5 tabular">{(v.battery_soc * 100).toFixed(0)}%</td>
                        <td className="py-0.5 tabular">{Math.round(v.payload_power_w)} W</td>
                        <td className="py-0.5 tabular">{Math.round(v.tokens_per_s).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1 text-[10px] text-text-lo">
                  The Live Telemetry strip now shows only the variant curves — the live
                  trace returns when you stop. Starting a new comparison below replaces
                  this one.
                </p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <Section title="Dimension">
                <div className="flex flex-col gap-1">
                  {(options?.dimensions ?? []).map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => selectDim(d)}
                      aria-current={d.id === dimId ? 'true' : undefined}
                      className={
                        'flex items-baseline justify-between rounded border px-2 py-1.5 text-left text-[11px] ' +
                        (d.id === dimId
                          ? 'border-accent bg-bg-card-hi text-text-hi'
                          : 'border-border-weak bg-bg-inset/40 text-text-md hover:border-border-med hover:text-text-hi')
                      }
                    >
                      <span>{d.label}</span>
                      <span className="text-[9px] uppercase tracking-[0.08em] text-text-lo">{d.group}</span>
                    </button>
                  ))}
                </div>
              </Section>

              <div className="flex flex-col gap-3">
                {dim && (
                  <Section title={`Values · pick 2–${MAX_PICK}`}>
                    <div className="flex flex-col gap-1">
                      {dim.values.map((c) => {
                        const idx = picked.indexOf(c.id)
                        const isCurrent = String(c.id) === String(dim.current)
                        return (
                          <ValueChip
                            key={String(c.id)}
                            choice={c}
                            pickedIndex={idx}
                            isCurrent={isCurrent}
                            disabled={idx < 0 && picked.length >= MAX_PICK}
                            onToggle={() => toggleValue(c.id)}
                          />
                        )
                      })}
                    </div>
                  </Section>
                )}

                <button
                  type="button"
                  data-testid="compare-run"
                  onClick={() => void onStart()}
                  disabled={!dim || picked.length < 2 || busy}
                  className="flex items-center justify-center gap-2 rounded border border-accent/60 bg-accent/15
                             px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.10em] text-accent
                             hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {busy
                    ? <><Loader2 size={13} className="animate-spin" /> Starting…</>
                    : <><Play size={13} strokeWidth={2} /> {active ? 'Restart with selection' : 'Start live comparison'}</>}
                </button>
                {picked.length < 2 && (
                  <span className="text-[10px] text-text-lo">
                    Select at least two values to compare.
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-[0.10em] text-text-lo">{title}</div>
      {children}
    </div>
  )
}

function ValueChip({
  choice, pickedIndex, isCurrent, disabled, onToggle,
}: {
  choice: CompareChoice
  pickedIndex: number
  isCurrent: boolean
  disabled: boolean
  onToggle: () => void
}) {
  const picked = pickedIndex >= 0
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      aria-pressed={picked}
      className={
        'flex items-center gap-2 rounded border px-2 py-1.5 text-left text-[11px] transition-colors ' +
        (picked
          ? 'border-border-focus bg-bg-card-hi text-text-hi'
          : 'border-border-weak bg-bg-inset/40 text-text-md hover:border-border-med') +
        (disabled ? ' cursor-not-allowed opacity-40' : '')
      }
    >
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-full ring-1 ring-white/10"
        style={{ background: picked ? COMPARE_PALETTE[pickedIndex] : 'transparent' }}
      />
      <span className="min-w-0 flex-1 truncate">{choice.label}</span>
      {isCurrent && (
        <span className="shrink-0 text-[8px] uppercase tracking-[0.08em] text-accent">live</span>
      )}
    </button>
  )
}
