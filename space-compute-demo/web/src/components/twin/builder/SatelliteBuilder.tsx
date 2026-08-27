import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Loader2, Rocket, X } from 'lucide-react'
import { useSatelliteAssets } from '../../../hooks/useSatelliteAssets'
import { useSatelliteBuild } from '../../../hooks/useSatelliteBuild'
import { useBuilderStore } from '../../../store/useBuilderStore'
import { useDemoStore } from '../../../store/demoStore'
import { GPU_SLOT_TINT, slotGroups } from '../../../data/satConfigOptions'
import type { GpuType } from '../../../types/messages'
import { StepAsset } from './StepAsset'
import { StepStructure } from './StepStructure'
import { StepPayload } from './StepPayload'
import { StepWorkload } from './StepWorkload'

const STEPS = [
  { key: 'asset',     title: 'Platform',  blurb: 'Which satellite to build on' },
  { key: 'structure', title: 'Structure', blurb: 'Power · thermal · orbit' },
  { key: 'payload',   title: 'Payload',   blurb: 'A GPU per bay slot' },
  { key: 'workload',  title: 'Workload',  blurb: 'What it computes' },
] as const

/**
 * SatelliteBuilder — the Twin page's build flow: pick a vendor platform, spec
 * its structure (power / thermal / orbit), fit each payload slot, choose the
 * job schedule, then Run.
 *
 * Nothing touches the live satellite until Run. Every edit re-runs the
 * backend DRY-RUN instead (POST /satellite_build/preview), which commissions
 * the draft on a detached engine — so the summary rail's margins and the
 * workload step's fit verdicts are the physics engine's own answers about the
 * satellite being designed, and Run cannot surprise you. Run itself is one
 * atomic POST: hull + loadout + slots + schedule land together, the USD
 * regenerates, and Kit reloads the model.
 */
export function SatelliteBuilder() {
  const closeBuilder = useBuilderStore((s) => s.closeBuilder)
  const { assets, activeId, offline } = useSatelliteAssets()
  const build = useSatelliteBuild(assets)
  const {
    draft, asset, fittedCount, preview, previewing, submitting,
    selectAsset, patchConfig, patchGeometry, setSlot, fillSlots,
    setWorkload, setAttitude, submit,
  } = build

  const [step, setStep] = useState(0)
  // `undefined` = "follow the platform's own card"; picking a brush (including
  // the Empty eraser, hence the distinct null) pins it until the platform
  // changes. Derived rather than synced in an effect so there is never a
  // render where the brush belongs to the previous platform.
  const [brush, setBrush] = useState<GpuType | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const activeBrush = brush === undefined ? (asset?.default_gpu ?? 'H100') : brush

  // Open on whatever the satellite is already flying — and when that IS one
  // of the catalogued platforms, seed the whole draft from the live loadout so
  // "rebuild" starts from the satellite in orbit rather than from the crate.
  const live = useDemoStore((s) => s.lastState)
  useEffect(() => {
    if (draft || assets.length === 0) return
    const seed = assets.find((a) => a.id === activeId) ?? assets[0]
    selectAsset(seed, seed.id === activeId && live ? {
      config: live.satellite_config,
      geometry: live.twin_geometry,
      slots: live.satellite_config?.gpu_slots,
      gpuCount: live.satellite?.gpu_count,
      workload_profile: live.workload_profile,
      attitude_mode: live.satellite?.attitude_mode,
    } : undefined)
  }, [assets, activeId, draft, live, selectAsset])

  const canAdvance = step !== 2 || fittedCount > 0
  const last = step === STEPS.length - 1

  const run = useCallback(async () => {
    setError(null)
    const res = await submit()
    if (res.ok && res.regenerated) {
      closeBuilder()
    } else if (res.ok) {
      setError('Satellite commissioned, but the 3D model failed to regenerate — '
             + 'the viewport may still show the previous geometry (see backend log).')
    } else {
      setError('Commissioning failed — backend offline or invalid configuration.')
    }
  }, [submit, closeBuilder])

  const profiles = preview?.profiles ?? []

  return (
    <div
      data-testid="satellite-builder"
      className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded border border-border-weak
                 bg-bg-card font-sans"
    >
      {/* Header — step rail. */}
      <div className="flex items-center gap-4 border-b border-border-weak px-4 py-3">
        <span className="flex items-center gap-2 text-[13px] uppercase tracking-[0.10em] text-text-md">
          <Rocket size={16} strokeWidth={1.8} className="text-text-md" />
          Satellite Builder
        </span>
        <div className="flex flex-1 items-center gap-2">
          {STEPS.map((s, i) => (
            <button
              key={s.key}
              type="button"
              data-testid={`build-step-${s.key}`}
              // Steps behind you are free to revisit; ahead is gated by the
              // same rule as Next (a bay with no cards is not a satellite).
              disabled={i > step && !canAdvance}
              onClick={() => setStep(i)}
              className={`flex items-center gap-2 rounded border px-3 py-2 text-[13px] transition-colors ${
                i === step
                  ? 'border-accent bg-accent/15 text-text-hi'
                  : i < step
                    ? 'border-border-weak bg-bg-inset/40 text-text-md hover:bg-bg-card-hi'
                    : 'border-border-weak bg-bg-inset/20 text-text-faint hover:text-text-md'
              }`}
            >
              <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${
                i <= step ? 'bg-accent text-bg-app' : 'bg-bg-card-hi text-text-lo'
              }`}>
                {i + 1}
              </span>
              {s.title}
              <span className="hidden text-[12px] text-text-faint xl:inline">· {s.blurb}</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={closeBuilder}
          className="rounded p-1.5 text-text-md hover:bg-bg-card-hi hover:text-text-hi"
          aria-label="close satellite builder"
          title="Skip the builder and fly the current satellite"
        >
          <X size={17} strokeWidth={1.8} />
        </button>
      </div>

      {offline && (
        <div className="mx-4 mt-3 rounded border border-warn/40 bg-warn/10 px-3.5 py-2.5 text-[13px] text-warn">
          Backend offline — start the FastAPI server (port 8001) to build a satellite.
        </div>
      )}
      {error && (
        <div className="mx-4 mt-3 rounded border border-err/40 bg-err/10 px-3.5 py-2.5 text-[13px] text-err">
          {error}
        </div>
      )}

      {/* Body — step content + the running summary. */}
      <div className="flex min-h-0 flex-1 gap-4 overflow-hidden p-4">
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {step === 0 && (
            <StepAsset
              assets={assets}
              selected={draft?.asset ?? null}
              activeId={activeId}
              onPick={(a) => { selectAsset(a); setBrush(undefined); setError(null) }}
            />
          )}
          {step === 1 && asset && draft && (
            <StepStructure
              asset={asset}
              config={draft.config}
              geometry={draft.geometry}
              attitude={draft.attitude_mode}
              onConfig={patchConfig}
              onGeometry={patchGeometry}
              onAttitude={setAttitude}
            />
          )}
          {step === 2 && asset && draft && (
            <StepPayload
              asset={asset}
              slots={draft.slots}
              onSlot={setSlot}
              onFill={fillSlots}
              brush={activeBrush}
              onBrush={setBrush}
            />
          )}
          {step === 3 && draft && (
            <StepWorkload
              profiles={profiles}
              selected={draft.workload_profile}
              loading={previewing && profiles.length === 0}
              onPick={setWorkload}
            />
          )}
          {!asset && !offline && (
            <div className="flex h-full items-center justify-center gap-2 text-[13px] text-text-lo">
              <Loader2 size={16} className="animate-spin text-accent" /> Loading platforms…
            </div>
          )}
        </div>

        <BuildSummary build={build} />
      </div>

      {/* Footer — navigation. */}
      <div className="flex items-center justify-between border-t border-border-weak px-4 py-3">
        <button
          type="button"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
          className="flex items-center gap-1.5 rounded border border-border-weak px-4 py-2 text-[13px]
                     text-text-md hover:bg-bg-card-hi hover:text-text-hi disabled:opacity-30"
        >
          <ChevronLeft size={14} strokeWidth={2} /> Back
        </button>

        <span className={`text-[12px] ${step === 2 && fittedCount === 0 ? 'text-text-md' : 'text-text-lo'}`}>
          {step === 2 && fittedCount === 0
            ? 'Fit at least one card to continue.'
            : `Step ${step + 1} of ${STEPS.length} · nothing is applied until you press Run.`}
        </span>

        {last ? (
          <button
            type="button"
            data-testid="build-run"
            onClick={() => void run()}
            disabled={!draft || fittedCount === 0 || submitting || offline}
            className="flex items-center gap-2 rounded border border-accent bg-accent/20 px-5 py-2
                       text-[13px] uppercase tracking-[0.08em] text-text-hi hover:bg-accent/30
                       disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting
              ? <><Loader2 size={14} className="animate-spin" /> Commissioning…</>
              : <><Rocket size={14} strokeWidth={2} /> Run</>}
          </button>
        ) : (
          <button
            type="button"
            data-testid="build-next"
            onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
            disabled={!draft || !canAdvance}
            className="flex items-center gap-1.5 rounded border border-accent/60 bg-accent/10 px-5 py-2
                       text-[13px] text-text-hi hover:bg-accent/20 disabled:opacity-30"
          >
            Next <ChevronRight size={14} strokeWidth={2} />
          </button>
        )}
      </div>
    </div>
  )
}

/** The running spec — what the draft satellite IS, and whether the physics
 *  says it works. Visible in every step so a change in one step's numbers is
 *  never a surprise in another's. */
function BuildSummary({ build }: { build: ReturnType<typeof useSatelliteBuild> }) {
  const { draft, asset, preview, previewing, fittedCount } = build
  const stats = preview?.stats
  const active = preview?.profiles.find((p) => p.id === draft?.workload_profile)
  const groups = useMemo(() => slotGroups(draft?.slots ?? []), [draft?.slots])

  if (!asset || !draft) return null

  return (
    <div className="flex w-[300px] shrink-0 flex-col gap-2.5 overflow-y-auto rounded-md border
                    border-border-weak bg-bg-inset/30 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] uppercase tracking-[0.12em] text-text-md">Build summary</span>
        {previewing && <Loader2 size={13} className="animate-spin text-accent" />}
      </div>

      <div className="flex flex-col gap-0.5">
        <span className="text-[16px] font-medium text-text-hi">{asset.name}</span>
        <span className="text-[12px] text-text-lo">{asset.vendor} · {asset.architecture} hull</span>
      </div>

      {/* Payload bay at a glance — the colours match the slot grid and the
          marker bars on the 3D blades. */}
      <div className="flex flex-wrap gap-1">
        {groups.length === 0 ? (
          <span className="text-[12px] text-err">No cards fitted</span>
        ) : groups.map((g) => (
          <span key={g.gpu}
                className="flex items-center gap-1.5 rounded border border-border-weak bg-bg-card-hi px-2 py-1
                           font-mono text-[12px] text-text-hi">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: GPU_SLOT_TINT[g.gpu] }} />
            {g.count}×{g.gpu}
          </span>
        ))}
      </div>

      <Line k="Slots fitted" v={`${fittedCount} / ${asset.slot_count}`} />
      <Line k="Compute" v={stats ? `${stats.compute_pflops.toFixed(1)} PF` : '—'} />
      <Line k="Peak payload" v={stats ? `${(stats.payload_peak_w / 1000).toFixed(2)} kW` : '—'} />
      <Line k="Platform" v={stats ? `${stats.platform_power_w} W` : '—'} />
      <Divider />
      <Line k="Solar area" v={stats ? `${stats.solar_area_m2} m²` : '—'} />
      <Line k="Peak solar" v={stats ? `${(stats.peak_solar_w / 1000).toFixed(1)} kW` : '—'} />
      <Line k="Battery" v={stats ? `${(stats.battery_capacity_wh / 1000).toFixed(1)} kWh` : '—'} />
      <Line k="Radiator" v={stats ? `${stats.radiator_area_m2} m²` : '—'} />
      <Line k="Pointing" v={draft.attitude_mode} />
      <Divider />

      {/* The verdict — the same design check the live satellite runs. */}
      <div className={`mt-auto flex flex-col gap-1.5 rounded border px-3 py-2.5 ${
        !active ? 'border-border-weak bg-bg-inset/40'
        : active.fit === 'ok' ? 'border-ok/40 bg-ok/10'
        : active.fit === 'tight' ? 'border-warn/40 bg-warn/10'
        : 'border-err/40 bg-err/10'
      }`}>
        <span className="flex items-baseline justify-between text-[12px]">
          <span className="uppercase tracking-[0.08em] text-text-lo">Design check</span>
          <span className={`font-mono uppercase ${
            !active ? 'text-text-lo'
            : active.fit === 'ok' ? 'text-ok'
            : active.fit === 'tight' ? 'text-warn' : 'text-err'}`}>
            {active?.fit ?? '—'}
          </span>
        </span>
        <Line k="Schedule" v={active?.label ?? draft.workload_profile} />
        <Line k="Power" v={active ? `${active.power_margin_pct >= 0 ? '+' : ''}${active.power_margin_pct}%` : '—'} />
        <Line k="Thermal" v={active ? `${active.thermal_margin_pct >= 0 ? '+' : ''}${active.thermal_margin_pct}%` : '—'} />
        {active?.fit === 'exceeds' && (
          <span className="text-[11px] leading-snug text-err">
            This satellite cannot sustain that schedule — add wings / radiator, or fit fewer cards.
            You can still fly it and watch the alarms.
          </span>
        )}
      </div>
    </div>
  )
}

function Line({ k, v }: { k: string; v: string }) {
  return (
    <span className="flex items-baseline justify-between gap-3 text-[12px]">
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className="truncate font-mono tabular-nums text-text-hi">{v}</span>
    </span>
  )
}

function Divider() {
  return <span className="my-1 h-px w-full bg-border-weak" />
}
