import { Activity, Cpu, Maximize2, Snowflake, Sun } from 'lucide-react'
import { Card } from '../primitives'
import { hasFixedWings } from '../../data/satConfigOptions'
import { useDemoStore } from '../../store/demoStore'
import { useTwinGeometry, GEOM_RANGE } from '../../hooks/useTwinGeometry'
import { WorkloadPanel } from './WorkloadPanel'
import {
  GPU_OPTIONS,
  RADIATOR_MATERIAL_OPTIONS,
  RADIATOR_SIZE_OPTIONS,
  SOLAR_MATERIAL_OPTIONS,
  SOLAR_SIZE_OPTIONS,
} from '../../data/satConfigOptions'
import { useSatConfig } from '../../hooks/useSatConfig'
import { ConfigDropdown } from './ConfigDropdown'
import { DesignSummary } from './DesignSummary'

/**
 * Configurator — the right-rail "design lab" where the viewer reconfigures
 * the satellite's three swappable hardware modules. Each dropdown change
 * fires `useSatConfig.update`, which writes to the telemetry store
 * (Phase 1 = local only; Phase 2 will also dispatch a `set_config` WS
 * envelope so backend recomputes physics).
 *
 * Live Deltas block sits below the dropdowns and reflects the delta of
 * key derived stats vs. the baseline loadout (defined in
 * SAT_CONFIG_BASELINE). Recomputes synchronously via deriveStats().
 */
export function Configurator() {
  const { cfg, update } = useSatConfig()

  return (
    <Card dense className="h-full flex flex-col min-h-0 overflow-y-auto">
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
          Hardware Configurator
        </span>
        <span className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          Twin · Live
        </span>
      </div>

      <Section title="Compute" icon={<Cpu size={12} strokeWidth={1.8} className="text-accent" />}>
        <ConfigDropdown
          label="GPU"
          value={cfg.gpu}
          options={GPU_OPTIONS.map((o) => ({
            id:     o.id,
            label:  o.label,
            swatch: o.tint,
            meta:   `${o.pflops_per_card.toFixed(2)} PF · ${o.tdp_w} W`,
          }))}
          onChange={(v) => update({ gpu: v })}
        />
      </Section>

      <Section title="Solar Array" icon={<Sun size={12} strokeWidth={1.8} className="text-accent" />}>
        <ConfigDropdown
          label="Material"
          value={cfg.solar_material}
          options={SOLAR_MATERIAL_OPTIONS.map((o) => ({
            id:     o.id,
            label:  o.label,
            swatch: o.tint,
            meta:   `η ${(o.efficiency * 100).toFixed(0)}% · ${o.density_kg_m2} kg/m²`,
          }))}
          onChange={(v) => update({ solar_material: v })}
        />
        <ConfigDropdown
          label="Size"
          value={cfg.solar_size}
          options={SOLAR_SIZE_OPTIONS.map((o) => ({
            id:    o.id,
            label: o.label,
            meta:  `${o.area_m2_per_panel} m² × ${o.panel_count}`,
          }))}
          onChange={(v) => update({ solar_size: v })}
        />
      </Section>

      <Section title="Radiator" icon={<Snowflake size={12} strokeWidth={1.8} className="text-accent" />}>
        <ConfigDropdown
          label="Material"
          value={cfg.radiator_material}
          options={RADIATOR_MATERIAL_OPTIONS.map((o) => ({
            id:     o.id,
            label:  o.label,
            swatch: o.tint,
            meta:   `ε ${o.emissivity.toFixed(2)}`,
          }))}
          onChange={(v) => update({ radiator_material: v })}
        />
        <ConfigDropdown
          label="Size"
          value={cfg.radiator_size}
          options={RADIATOR_SIZE_OPTIONS.map((o) => ({
            id:    o.id,
            label: o.label,
            meta:  `${o.area_m2_per_panel} m² × 2`,
          }))}
          onChange={(v) => update({ radiator_size: v })}
        />
      </Section>

      <GeometryControls />

      <Section title="Workload" icon={<Activity size={12} strokeWidth={1.8} className="text-accent" />}>
        <WorkloadPanel />
      </Section>

      <DesignSummary />
    </Card>
  )
}

const round2 = (n: number) => Math.round(n * 100) / 100

/** Deployable-geometry controls (Feature 3): add/remove solar clusters per
 * side, and resize / reshape the radiators. Each step POSTs /twin_geometry,
 * which regenerates the USD model and bumps the version for Kit to reload. */
function GeometryControls() {
  const { geom, update } = useTwinGeometry()
  const R = GEOM_RANGE
  const solar = geom.solar_clusters_per_side
  const long  = geom.radiator_long
  const ratio = geom.radiator_ratio
  // Hull architectures (LUMID / dish) fly integrated panels — the wing
  // stepper has nothing to resize there.
  const fixedWings = hasFixedWings(geom)
  return (
    <Section title="Deployables" icon={<Maximize2 size={12} strokeWidth={1.8} className="text-accent" />}>
      <Stepper
        label="Solar / side"
        value={fixedWings ? 'hull' : `${solar}×`}
        onDec={() => update({ solar_clusters_per_side: solar - 1 })}
        onInc={() => update({ solar_clusters_per_side: solar + 1 })}
        decDisabled={fixedWings || solar <= R.solar_clusters_per_side.min}
        incDisabled={fixedWings || solar >= R.solar_clusters_per_side.max}
      />
      <Stepper
        label="Radiator size"
        value={`${(long * 1.8).toFixed(1)} m`}
        onDec={() => update({ radiator_long: round2(long - R.radiator_long.step) })}
        onInc={() => update({ radiator_long: round2(long + R.radiator_long.step) })}
        decDisabled={long <= R.radiator_long.min + 1e-6}
        incDisabled={long >= R.radiator_long.max - 1e-6}
      />
      <Stepper
        label="Radiator ratio"
        value={`1:${ratio.toFixed(1)}`}
        onDec={() => update({ radiator_ratio: round2(ratio - R.radiator_ratio.step) })}
        onInc={() => update({ radiator_ratio: round2(ratio + R.radiator_ratio.step) })}
        decDisabled={ratio <= R.radiator_ratio.min + 1e-6}
        incDisabled={ratio >= R.radiator_ratio.max - 1e-6}
      />
      {geom.architecture === 'redwire' && <SolarDeployControl />}
      <AttitudeSpinControl />
    </Section>
  )
}

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://localhost:8001'

/** Roll-out array control (redwire only): the flexible blanket wings reel
 * out of / into the bay edges. POST /solar_deploy animates the fraction on
 * the backend over ~12 s; solar production and the Kit close-up's wing
 * stretch follow it live, so retracting genuinely starves the satellite. */
function SolarDeployControl() {
  const frac = useDemoStore(
    (s) => s.lastState?.satellite?.solar_deploy_frac,
  ) ?? 1
  const deployed = frac >= 0.5
  const moving = frac > 0.02 && frac < 0.98
  const toggle = async () => {
    try {
      await fetch(`${BACKEND_HTTP}/solar_deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'toggle' }),
      })
    } catch {
      /* backend offline — control is inert in the local fallback */
    }
  }
  return (
    <div
      data-testid="solar-deploy"
      className="flex items-center justify-between rounded border border-border-weak bg-bg-inset/40 px-2 py-1"
    >
      <span className="text-[11px] text-text-md">Roll-out array</span>
      <div className="flex items-center gap-2">
        <span className={`font-mono tabular-nums text-[11px] ${moving ? 'text-accent' : 'text-text-hi'}`}>
          {Math.round(frac * 100)}%
        </span>
        <button
          type="button"
          onClick={toggle}
          className="rounded border border-border-weak px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-md hover:bg-bg-cardHi hover:text-text-hi"
        >
          {deployed ? 'Retract' : 'Deploy'}
        </button>
      </div>
    </div>
  )
}

/** Reaction-wheel demo: spin the whole body 360° about any centre-of-mass
 * axis at a legible 1 rpm — the X/Y/Z toggles combine into a slow tumble.
 * POST /attitude_spin per axis; the Kit close-up integrates the angles per
 * frame. Display-only (the sun-tracking power model is unaffected). */
function AttitudeSpinControl() {
  const raw = useDemoStore(
    (s) => s.lastState?.satellite?.attitude_spin_dps,
  )
  const rates: number[] = Array.isArray(raw) ? raw : [0, 0, typeof raw === 'number' ? raw : 0]
  const anySpin = rates.some((r) => r > 0)
  const toggle = async (axis: 'x' | 'y' | 'z') => {
    try {
      await fetch(`${BACKEND_HTTP}/attitude_spin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'toggle', axis }),
      })
    } catch {
      /* backend offline — control is inert in the local fallback */
    }
  }
  const axes: Array<'x' | 'y' | 'z'> = ['x', 'y', 'z']
  return (
    <div
      data-testid="attitude-spin"
      className="flex items-center justify-between rounded border border-border-weak bg-bg-inset/40 px-2 py-1"
    >
      <span className="text-[11px] text-text-md">Reaction wheels</span>
      <div className="flex items-center gap-1.5">
        <span className={`font-mono tabular-nums text-[11px] ${anySpin ? 'text-accent' : 'text-text-lo'}`}>
          {anySpin ? '1 rpm' : 'idle'}
        </span>
        {axes.map((ax, i) => (
          <button
            key={ax}
            type="button"
            onClick={() => toggle(ax)}
            aria-pressed={rates[i] > 0}
            className={`w-6 rounded border px-0 py-0.5 text-[10px] uppercase tracking-[0.08em] ${
              rates[i] > 0
                ? 'border-accent/70 bg-accent/15 text-accent'
                : 'border-border-weak text-text-md hover:bg-bg-cardHi hover:text-text-hi'
            }`}
          >
            {ax.toUpperCase()}
          </button>
        ))}
      </div>
    </div>
  )
}

function Stepper({
  label, value, onDec, onInc, decDisabled, incDisabled,
}: {
  label: string; value: string
  onDec: () => void; onInc: () => void
  decDisabled?: boolean; incDisabled?: boolean
}) {
  const btn = 'flex h-5 w-5 items-center justify-center rounded border border-border-weak text-text-md ' +
    'hover:bg-bg-cardHi hover:text-text-hi disabled:opacity-30 disabled:cursor-not-allowed'
  return (
    <div className="flex items-center justify-between rounded border border-border-weak bg-bg-inset/40 px-2 py-1">
      <span className="text-[11px] text-text-md">{label}</span>
      <div className="flex items-center gap-1.5">
        <button type="button" onClick={onDec} disabled={decDisabled} className={btn} aria-label={`decrease ${label}`}>−</button>
        <span className="w-12 text-right font-mono tabular-nums text-[11px] text-text-hi">{value}</span>
        <button type="button" onClick={onInc} disabled={incDisabled} className={btn} aria-label={`increase ${label}`}>+</button>
      </div>
    </div>
  )
}

function Section({
  title, icon, children,
}: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mt-3 first:mt-2">
      <div className="mb-1 flex items-center gap-1.5">
        {icon}
        <span className="text-[10px] uppercase tracking-[0.12em] text-text-md">
          {title}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {children}
      </div>
    </div>
  )
}
