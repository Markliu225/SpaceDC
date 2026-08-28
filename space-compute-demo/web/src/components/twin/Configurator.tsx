import { BatteryCharging, Compass, Cpu, Maximize2, Snowflake, Sun } from 'lucide-react'
import { Card } from '../primitives'
import { batteryCapacityWh, hasFixedWings, slotGroups, GPU_SLOT_TINT } from '../../data/satConfigOptions'
import { useDemoStore } from '../../store/demoStore'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import { useTwinGeometry, GEOM_RANGE } from '../../hooks/useTwinGeometry'
import { WorkloadPanel } from './WorkloadPanel'
import {
  ATTITUDE_MODES,
  BATTERY_MATERIAL_OPTIONS,
  BATTERY_SIZE_OPTIONS,
  GPU_OPTIONS,
  RADIATOR_MATERIAL_OPTIONS,
  RADIATOR_SIZE_OPTIONS,
  SOLAR_MATERIAL_OPTIONS,
  SOLAR_SIZE_OPTIONS,
} from '../../data/satConfigOptions'
import { useSatConfig } from '../../hooks/useSatConfig'
import { ConfigDropdown } from './ConfigDropdown'
import { DesignSummary } from './DesignSummary'
import { Stepper } from './Stepper'

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

      <Section title="Compute" icon={<Cpu size={12} strokeWidth={1.8} className="text-text-md" />}>
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
        <BayLoadout />
        {/* Workload lives with Compute — the GPU and the job it runs are one
            concern. */}
        <WorkloadPanel />
      </Section>

      <Section title="Solar Array" icon={<Sun size={12} strokeWidth={1.8} className="text-text-md" />}>
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

      <Section title="Radiator" icon={<Snowflake size={12} strokeWidth={1.8} className="text-text-md" />}>
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

      <Section title="Battery" icon={<BatteryCharging size={12} strokeWidth={1.8} className="text-text-md" />}>
        <ConfigDropdown
          label="Chemistry"
          value={cfg.battery_material}
          options={BATTERY_MATERIAL_OPTIONS.map((o) => ({
            id:     o.id,
            label:  o.label,
            swatch: o.tint,
            meta:   `${o.density_wh_kg} Wh/kg · η ${(o.efficiency * 100).toFixed(0)}%`,
          }))}
          onChange={(v) => update({ battery_material: v })}
        />
        <ConfigDropdown
          label="Pack size"
          value={cfg.battery_size}
          options={BATTERY_SIZE_OPTIONS.map((o) => ({
            id:    o.id,
            label: o.label,
            meta:  `${o.mass_kg} kg → ${(batteryCapacityWh(cfg.battery_material, o.id) / 1000).toFixed(1)} kWh`,
          }))}
          onChange={(v) => update({ battery_size: v })}
        />
        <div className="px-0.5 text-[10px] tabular text-text-lo">
          Capacity {(batteryCapacityWh(cfg.battery_material, cfg.battery_size) / 1000).toFixed(1)} kWh
        </div>
      </Section>

      <GeometryControls />

      <Section title="Attitude" icon={<Compass size={12} strokeWidth={1.8} className="text-text-md" />}>
        <AttitudeControl />
      </Section>

      <DesignSummary />
    </Card>
  )
}

/** The fitted payload bay, when the satellite was BUILT slot by slot. The GPU
 *  dropdown above can only show one model, so a mixed bay would otherwise be
 *  invisible here — and switching that dropdown re-fits every populated slot,
 *  which the viewer should be able to see coming. */
function BayLoadout() {
  const slots = useTelemetryStore((s) => s.satConfig.gpu_slots) ?? []
  if (slots.length === 0) return null
  const groups = slotGroups(slots)
  const fitted = groups.reduce((n, g) => n + g.count, 0)
  return (
    <div data-testid="bay-loadout"
         className="flex items-center justify-between gap-2 rounded border border-border-weak
                    bg-bg-inset/40 px-2 py-1 text-[10px]">
      <span className="uppercase tracking-[0.08em] text-text-lo">Bay</span>
      <span className="flex items-center gap-1.5">
        {groups.map((g) => (
          <span key={g.gpu} className="flex items-center gap-1 font-mono tabular-nums text-text-hi">
            <span className="h-2 w-2 rounded-sm" style={{ background: GPU_SLOT_TINT[g.gpu] }} />
            {g.count}×{g.gpu}
          </span>
        ))}
        <span className="text-text-lo">· {fitted}/{slots.length}</span>
      </span>
    </div>
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
    <Section title="Deployables" icon={<Maximize2 size={12} strokeWidth={1.8} className="text-text-md" />}>
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
    </Section>
  )
}

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://127.0.0.1:8001'

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
          className="rounded border border-border-weak px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-md hover:bg-bg-card-hi hover:text-text-hi"
        >
          {deployed ? 'Retract' : 'Deploy'}
        </button>
      </div>
    </div>
  )
}

/** Attitude control: pick a fixed pointing mode (Sun / Nadir / Ram /
 * Inertial) OR spin the reaction wheels about the X/Y/Z centre-of-mass axes
 * at 1 rpm. The two are mutually exclusive — selecting a mode zeroes the
 * wheels (backend), and touching a wheel drops back to 'free' so no mode
 * stays highlighted. Both POST to the backend; the Kit close-up either eases
 * the body to the pointing target or integrates the tumble. Display-only. */
function AttitudeControl() {
  const mode = useDemoStore((s) => s.lastState?.satellite?.attitude_mode) ?? 'free'
  const raw = useDemoStore((s) => s.lastState?.satellite?.attitude_spin_dps)
  const incidence = useDemoStore((s) => s.lastState?.satellite?.solar_incidence)
  const sunlit = useDemoStore((s) => s.lastState?.satellite?.sunlit)
  const rates: number[] = Array.isArray(raw) ? raw : [0, 0, typeof raw === 'number' ? raw : 0]
  const anySpin = rates.some((r) => r > 0)
  const incPct = Math.round((incidence ?? 0) * 100)

  const setMode = async (next: string) => {
    // Clicking the active mode toggles back to free (wheels available again).
    const target = mode === next ? 'free' : next
    try {
      await fetch(`${BACKEND_HTTP}/attitude_mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: target }),
      })
    } catch { /* backend offline — inert in the local fallback */ }
  }
  const toggleWheel = async (axis: 'x' | 'y' | 'z') => {
    try {
      await fetch(`${BACKEND_HTTP}/attitude_spin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'toggle', axis }),
      })
    } catch { /* backend offline — inert in the local fallback */ }
  }
  const axes: Array<'x' | 'y' | 'z'> = ['x', 'y', 'z']

  return (
    <div data-testid="attitude-control" className="flex flex-col gap-1.5">
      {/* Attitude → solar-collection readout: the physical link the modes
          drive. Sun-pointing holds ~100 %; a body-fixed nadir/ram/inertial
          array projects geometrically and can fall to 0 even in daylight. */}
      <div className="flex items-center justify-between px-0.5 text-[10px]">
        <span className="uppercase tracking-[0.08em] text-text-lo">Solar collection</span>
        <span className={'tabular font-semibold '
          + (!sunlit ? 'text-text-lo' : incPct >= 80 ? 'text-ok' : incPct >= 30 ? 'text-warn' : 'text-err')}>
          {!sunlit ? 'eclipse · 0%' : `${incPct}% incidence`}
        </span>
      </div>
      {/* Pointing-mode presets. */}
      <div className="grid grid-cols-4 gap-1">
        {ATTITUDE_MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            data-testid={`attitude-mode-${m.id}`}
            onClick={() => void setMode(m.id)}
            aria-pressed={mode === m.id}
            title={m.title}
            className={`rounded border px-1 py-1 text-[10px] tracking-[0.04em] ${
              mode === m.id
                ? 'border-accent/70 bg-accent/15 text-accent'
                : 'border-border-weak text-text-md hover:bg-bg-card-hi hover:text-text-hi'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      {/* Reaction wheels — highlighted only while free-tumbling. */}
      <div className="flex items-center justify-between rounded border border-border-weak bg-bg-inset/40 px-2 py-1">
        <span className="text-[11px] text-text-md">Reaction wheels</span>
        <div className="flex items-center gap-1.5">
          <span className={`font-mono tabular-nums text-[11px] ${anySpin ? 'text-accent' : 'text-text-lo'}`}>
            {anySpin ? '1 rpm' : mode !== 'free' ? 'held' : 'idle'}
          </span>
          {axes.map((ax, i) => (
            <button
              key={ax}
              type="button"
              data-testid={`attitude-wheel-${ax}`}
              onClick={() => void toggleWheel(ax)}
              aria-pressed={rates[i] > 0}
              className={`w-6 rounded border px-0 py-0.5 text-[10px] uppercase tracking-[0.08em] ${
                rates[i] > 0
                  ? 'border-accent/70 bg-accent/15 text-accent'
                  : 'border-border-weak text-text-md hover:bg-bg-card-hi hover:text-text-hi'
              }`}
            >
              {ax.toUpperCase()}
            </button>
          ))}
        </div>
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
