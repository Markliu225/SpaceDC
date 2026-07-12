import { Activity, Cpu, Maximize2, Snowflake, Sun } from 'lucide-react'
import { Card } from '../primitives'
import { hasFixedWings } from '../../data/satConfigOptions'
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
    </Section>
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
