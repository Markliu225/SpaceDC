import { Compass, Snowflake, Sun } from 'lucide-react'
import { useDemoStore } from '../../../store/demoStore'
import {
  ATTITUDE_MODES,
  BATTERY_MATERIAL_OPTIONS,
  BATTERY_SIZE_OPTIONS,
  RADIATOR_MATERIAL_OPTIONS,
  RADIATOR_SIZE_OPTIONS,
  SOLAR_MATERIAL_OPTIONS,
  SOLAR_SIZE_OPTIONS,
  batteryCapacityWh,
  hasFixedWings,
} from '../../../data/satConfigOptions'
import { ConfigDropdown } from '../ConfigDropdown'
import { Stepper } from '../Stepper'
import { BUILD_RANGE, type BuildGeometry } from '../../../hooks/useSatelliteBuild'
import type { SatelliteAssetInfo, SatelliteConfig } from '../../../types/messages'

const round2 = (n: number) => Math.round(n * 100) / 100

/**
 * Step 2 — STRUCTURE DESIGN: the power chain, the thermal chain and the
 * orbital attitude. Same knobs the live Configurator rail carries (solar,
 * battery, radiator, deployables, pointing), gathered here so the whole
 * satellite is specced before anything is committed to the engine.
 */
export function StepStructure({
  asset, config, geometry, attitude,
  onConfig, onGeometry, onAttitude,
}: {
  asset: SatelliteAssetInfo
  config: SatelliteConfig
  geometry: BuildGeometry
  attitude: string
  onConfig: (patch: Partial<SatelliteConfig>) => void
  onGeometry: (patch: Partial<BuildGeometry>) => void
  onAttitude: (mode: string) => void
}) {
  const R = BUILD_RANGE
  // Hull architectures (tile / dish) fly cells integrated into the body —
  // there is no wing to add segments to.
  const fixedWings = hasFixedWings({ ...geometry, architecture: asset.architecture })

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] leading-relaxed text-text-lo">
        <span className="text-text-hi">Satellite structure design</span> — the power chain, the
        thermal chain, and how the body points once it is on station. These are the same knobs
        the live Configurator carries; here they apply to the satellite you are building.
      </p>
      <div className="grid grid-cols-3 gap-3">
      <Column
        title="Power"
        icon={<Sun size={12} strokeWidth={1.8} className="text-accent" />}
        note="Cells, wing size and the pack that carries the satellite through eclipse."
      >
        <ConfigDropdown
          label="Solar material"
          value={config.solar_material}
          options={SOLAR_MATERIAL_OPTIONS.map((o) => ({
            id: o.id, label: o.label, swatch: o.tint,
            meta: `η ${(o.efficiency * 100).toFixed(0)}% · ${o.density_kg_m2} kg/m²`,
          }))}
          onChange={(v) => onConfig({ solar_material: v })}
        />
        <ConfigDropdown
          label="Solar size"
          value={config.solar_size}
          options={SOLAR_SIZE_OPTIONS.map((o) => ({
            id: o.id, label: o.label,
            meta: `${o.area_m2_per_panel} m² × ${o.panel_count}`,
          }))}
          onChange={(v) => onConfig({ solar_size: v })}
        />
        <Stepper
          label="Wing segments / side"
          value={fixedWings ? 'hull' : `${geometry.solar_clusters_per_side}×`}
          onDec={() => onGeometry({ solar_clusters_per_side: geometry.solar_clusters_per_side - 1 })}
          onInc={() => onGeometry({ solar_clusters_per_side: geometry.solar_clusters_per_side + 1 })}
          decDisabled={fixedWings || geometry.solar_clusters_per_side <= R.solar_clusters_per_side.min}
          incDisabled={fixedWings || geometry.solar_clusters_per_side >= R.solar_clusters_per_side.max}
        />
        <ConfigDropdown
          label="Battery chemistry"
          value={config.battery_material}
          options={BATTERY_MATERIAL_OPTIONS.map((o) => ({
            id: o.id, label: o.label, swatch: o.tint,
            meta: `${o.density_wh_kg} Wh/kg · η ${(o.efficiency * 100).toFixed(0)}%`,
          }))}
          onChange={(v) => onConfig({ battery_material: v })}
        />
        <ConfigDropdown
          label="Pack size"
          value={config.battery_size}
          options={BATTERY_SIZE_OPTIONS.map((o) => ({
            id: o.id, label: o.label,
            meta: `${o.mass_kg} kg → ${(batteryCapacityWh(config.battery_material, o.id) / 1000).toFixed(1)} kWh`,
          }))}
          onChange={(v) => onConfig({ battery_size: v })}
        />
        <Readout
          k="Pack capacity"
          v={`${(batteryCapacityWh(config.battery_material, config.battery_size) / 1000).toFixed(1)} kWh`}
        />
      </Column>

      <Column
        title="Thermal"
        icon={<Snowflake size={12} strokeWidth={1.8} className="text-accent" />}
        note="Emissivity and radiator area set how much compute the satellite can sustain."
      >
        <ConfigDropdown
          label="Radiator material"
          value={config.radiator_material}
          options={RADIATOR_MATERIAL_OPTIONS.map((o) => ({
            id: o.id, label: o.label, swatch: o.tint,
            meta: `ε ${o.emissivity.toFixed(2)}`,
          }))}
          onChange={(v) => onConfig({ radiator_material: v })}
        />
        <ConfigDropdown
          label="Radiator size"
          value={config.radiator_size}
          options={RADIATOR_SIZE_OPTIONS.map((o) => ({
            id: o.id, label: o.label, meta: `${o.area_m2_per_panel} m² × 2`,
          }))}
          onChange={(v) => onConfig({ radiator_size: v })}
        />
        <Stepper
          label="Panel span"
          value={`${(geometry.radiator_long * 1.8).toFixed(1)} m`}
          onDec={() => onGeometry({ radiator_long: round2(geometry.radiator_long - R.radiator_long.step) })}
          onInc={() => onGeometry({ radiator_long: round2(geometry.radiator_long + R.radiator_long.step) })}
          decDisabled={geometry.radiator_long <= R.radiator_long.min + 1e-6}
          incDisabled={geometry.radiator_long >= R.radiator_long.max - 1e-6}
        />
        <Stepper
          label="Panel ratio"
          value={`1:${geometry.radiator_ratio.toFixed(1)}`}
          onDec={() => onGeometry({ radiator_ratio: round2(geometry.radiator_ratio - R.radiator_ratio.step) })}
          onInc={() => onGeometry({ radiator_ratio: round2(geometry.radiator_ratio + R.radiator_ratio.step) })}
          decDisabled={geometry.radiator_ratio <= R.radiator_ratio.min + 1e-6}
          incDisabled={geometry.radiator_ratio >= R.radiator_ratio.max - 1e-6}
        />
      </Column>

      <Column
        title="Orbit & attitude"
        icon={<Compass size={12} strokeWidth={1.8} className="text-accent" />}
        note="Where the satellite flies, and how it holds itself there once commissioned."
      >
        <OrbitReadout />
        <div>
          <span className="mb-1 block text-[10px] uppercase tracking-[0.10em] text-text-lo">
            Pointing mode
          </span>
          <div className="grid grid-cols-2 gap-1">
            {ATTITUDE_MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                data-testid={`build-attitude-${m.id}`}
                onClick={() => onAttitude(m.id)}
                aria-pressed={attitude === m.id}
                title={m.title}
                className={`rounded border px-1 py-1.5 text-[10px] tracking-[0.04em] ${
                  attitude === m.id
                    ? 'border-accent/70 bg-accent/15 text-accent'
                    : 'border-border-weak text-text-md hover:bg-bg-card-hi hover:text-text-hi'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <p className="text-[10px] leading-relaxed text-text-faint">
          Sun-pointing holds the array near full incidence; a nadir / ram / inertial body
          projects geometrically and can collect nothing even in daylight. Reaction wheels
          stay available in the Configurator after commissioning.
        </p>
      </Column>
      </div>
    </div>
  )
}

/** The orbit the satellite will fly — owned by the constellation (Overview's
 *  orbit designer), so the builder reports it rather than re-editing it. */
function OrbitReadout() {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const fleet = useDemoStore((s) => s.lastState?.constellation)
  return (
    <div className="flex flex-col gap-1 rounded border border-border-weak bg-bg-inset/40 px-2 py-1.5">
      <Readout k="Orbit" v={sat ? `${sat.orbit_type} · ${Math.round(sat.altitude_km)} km` : '— —'} bare />
      <Readout k="Inclination" v={fleet ? `${fleet.inclination_deg.toFixed(1)}°` : '— —'} bare />
      <Readout k="Constellation" v={fleet?.name ?? '— —'} bare />
    </div>
  )
}

function Readout({ k, v, bare = false }: { k: string; v: string; bare?: boolean }) {
  return (
    <span className={'flex items-baseline justify-between gap-2 text-[10px] '
      + (bare ? '' : 'rounded border border-border-weak bg-bg-inset/40 px-2 py-1')}>
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className="truncate font-mono tabular-nums text-text-hi">{v}</span>
    </span>
  )
}

function Column({
  title, icon, note, children,
}: { title: string; icon: React.ReactNode; note: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border-weak bg-bg-inset/20 p-2.5">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-[10px] uppercase tracking-[0.12em] text-text-md">{title}</span>
      </div>
      <p className="text-[10px] leading-snug text-text-faint">{note}</p>
      {children}
    </div>
  )
}
