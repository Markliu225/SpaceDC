import { Compass, Snowflake, Sun } from 'lucide-react'
import { useDemoStore } from '../../../store/demoStore'
import {
  ATTITUDE_MODES,
  BATTERY_MATERIAL_OPTIONS,
  BATTERY_SIZE_OPTIONS,
  RADIATOR_MATERIAL_OPTIONS,
  SOLAR_MATERIAL_OPTIONS,
  batteryCapacityWh,
  hasFixedWings,
  radiatorEmitAreaM2,
  solarAreaM2,
  solarMaterial,
  radiatorMaterial,
} from '../../../data/satConfigOptions'
import { ConfigDropdown } from '../ConfigDropdown'
import { NumberField } from './NumberField'
import { BUILD_RANGE, type BuildGeometry } from '../../../hooks/useSatelliteBuild'
import type { SatelliteAssetInfo, SatelliteConfig } from '../../../types/messages'

/** Stage scale: the generator's radiator_long is in backbone units, and the
 *  model is authored at ×1.8 — so a span the viewer types in metres maps
 *  through this. Mirrors gen_twin_satellite.BACKBONE_SCALE. */
const BACKBONE_SCALE = 1.8

/**
 * Step 2 — STRUCTURE DESIGN: the power chain, the thermal chain and the
 * orbital attitude. The same concerns the live Configurator rail carries,
 * gathered here so the whole satellite is specced before anything is
 * committed to the engine.
 *
 * Panel SIZES are typed as real dimensions rather than picked from a tier:
 * wing segments per side and the radiator's span / aspect ratio are the
 * numbers the USD generator and the physics actually consume, so the area
 * readout under each field is the area the satellite will really fly.
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
  const geomFull = { ...geometry, architecture: asset.architecture }
  // Hull architectures (tile / dish) fly cells integrated into the body —
  // there is no wing to add segments to.
  const fixedWings = hasFixedWings(geomFull)

  const solarArea = solarAreaM2(geomFull)
  const emitArea = radiatorEmitAreaM2(geomFull)
  const peakSolarKw = (solarMaterial(config.solar_material).efficiency * solarArea * 1361) / 1000
  // Emission ceiling at the +60 °C safe-operating limit — the same
  // Stefan-Boltzmann line the engine's design check uses.
  const emitCeilingKw = (radiatorMaterial(config.radiator_material).emissivity
    * 5.67e-8 * emitArea * ((333.15 ** 4) - (250 ** 4))) / 1000
  const packKwh = batteryCapacityWh(config.battery_material, config.battery_size) / 1000

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <p className="text-[13px] leading-relaxed text-text-lo">
        <span className="text-text-hi">Satellite structure design</span> — the power chain, the
        thermal chain, and how the body points once it is on station. Panel sizes are typed in
        real units; the area each one produces updates as you go.
      </p>

      <div className="grid min-h-0 flex-1 grid-cols-3 gap-4">
        <Column
          title="Power"
          icon={<Sun size={15} strokeWidth={1.8} className="text-accent" />}
          note="Cells, wing size, and the pack that carries the satellite through eclipse."
        >
          <ConfigDropdown
            size="md"
            label="Solar material"
            value={config.solar_material}
            options={SOLAR_MATERIAL_OPTIONS.map((o) => ({
              id: o.id, label: o.label, swatch: o.tint,
              meta: `η ${(o.efficiency * 100).toFixed(0)}% · ${o.density_kg_m2} kg/m²`,
            }))}
            onChange={(v) => onConfig({ solar_material: v })}
          />
          <NumberField
            label="Wing segments / side"
            value={geometry.solar_clusters_per_side}
            min={R.solar_clusters_per_side.min}
            max={R.solar_clusters_per_side.max}
            step={R.solar_clusters_per_side.step}
            decimals={0}
            hint={`${solarArea.toFixed(1)} m² of cells`}
            disabled={fixedWings}
            disabledText="integrated in hull"
            onCommit={(v) => onGeometry({ solar_clusters_per_side: Math.round(v) })}
          />
          <ConfigDropdown
            size="md"
            label="Battery chemistry"
            value={config.battery_material}
            options={BATTERY_MATERIAL_OPTIONS.map((o) => ({
              id: o.id, label: o.label, swatch: o.tint,
              meta: `${o.density_wh_kg} Wh/kg · η ${(o.efficiency * 100).toFixed(0)}%`,
            }))}
            onChange={(v) => onConfig({ battery_material: v })}
          />
          <ConfigDropdown
            size="md"
            label="Pack size"
            value={config.battery_size}
            options={BATTERY_SIZE_OPTIONS.map((o) => ({
              id: o.id, label: o.label,
              meta: `${o.mass_kg} kg → ${(batteryCapacityWh(config.battery_material, o.id) / 1000).toFixed(1)} kWh`,
            }))}
            onChange={(v) => onConfig({ battery_size: v })}
          />
          <Derived rows={[
            ['Array area', `${solarArea.toFixed(1)} m²`],
            ['Peak generation', `${peakSolarKw.toFixed(2)} kW`],
            ['Pack capacity', `${packKwh.toFixed(1)} kWh`],
          ]} />
        </Column>

        <Column
          title="Thermal"
          icon={<Snowflake size={15} strokeWidth={1.8} className="text-accent" />}
          note="Emissivity and radiator area set how much compute the satellite can sustain."
        >
          <ConfigDropdown
            size="md"
            label="Radiator material"
            value={config.radiator_material}
            options={RADIATOR_MATERIAL_OPTIONS.map((o) => ({
              id: o.id, label: o.label, swatch: o.tint,
              meta: `ε ${o.emissivity.toFixed(2)}`,
            }))}
            onChange={(v) => onConfig({ radiator_material: v })}
          />
          {/* Typed in metres; the generator wants backbone units. */}
          <NumberField
            label="Panel span"
            value={round2(geometry.radiator_long * BACKBONE_SCALE)}
            min={round2(R.radiator_long.min * BACKBONE_SCALE)}
            max={round2(R.radiator_long.max * BACKBONE_SCALE)}
            step={round2(R.radiator_long.step * BACKBONE_SCALE)}
            unit="m"
            decimals={2}
            hint={`${(geometry.radiator_long * BACKBONE_SCALE / geometry.radiator_ratio).toFixed(2)} m wide`}
            onCommit={(v) => onGeometry({ radiator_long: round4(v / BACKBONE_SCALE) })}
          />
          <NumberField
            label="Aspect ratio (long : short)"
            value={geometry.radiator_ratio}
            min={R.radiator_ratio.min}
            max={R.radiator_ratio.max}
            step={R.radiator_ratio.step}
            decimals={1}
            hint={`1 : ${geometry.radiator_ratio.toFixed(1)}`}
            onCommit={(v) => onGeometry({ radiator_ratio: round2(v) })}
          />
          <Derived rows={[
            ['Emitting area', `${emitArea.toFixed(1)} m²`],
            ['Ceiling at +60 °C', `${emitCeilingKw.toFixed(2)} kW`],
            ['Panels', asset.architecture === 'redwire' ? '1 × both faces' : '2 × both faces'],
          ]} />
        </Column>

        <Column
          title="Orbit & attitude"
          icon={<Compass size={15} strokeWidth={1.8} className="text-accent" />}
          note="Where the satellite flies, and how it holds itself there once commissioned."
        >
          <OrbitReadout />
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] uppercase tracking-[0.10em] text-text-lo">
              Pointing mode
            </span>
            <div className="grid grid-cols-2 gap-2">
              {ATTITUDE_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  data-testid={`build-attitude-${m.id}`}
                  onClick={() => onAttitude(m.id)}
                  aria-pressed={attitude === m.id}
                  title={m.title}
                  className={`rounded border px-2 py-2.5 text-[13px] tracking-[0.02em] ${
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
          <p className="text-[12px] leading-relaxed text-text-faint">
            Sun-pointing holds the array near full incidence; a nadir / ram / inertial body
            projects geometrically and can collect nothing even in daylight. Reaction wheels
            stay available in the Configurator after commissioning.
          </p>
          <Derived rows={[
            ['Pointing', ATTITUDE_MODES.find((m) => m.id === attitude)?.label ?? attitude],
            ['Array tracking', attitude === 'sun' ? 'full incidence' : 'geometric projection'],
          ]} />
        </Column>
      </div>
    </div>
  )
}

const round2 = (n: number) => Math.round(n * 100) / 100
const round4 = (n: number) => Math.round(n * 1e4) / 1e4

/** The orbit the satellite will fly — owned by the constellation (Overview's
 *  orbit designer), so the builder reports it rather than re-editing it. */
function OrbitReadout() {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const fleet = useDemoStore((s) => s.lastState?.constellation)
  return (
    <div className="flex flex-col gap-1.5 rounded border border-border-weak bg-bg-inset/40 px-3 py-2.5">
      <Line k="Orbit" v={sat ? `${sat.orbit_type} · ${Math.round(sat.altitude_km)} km` : '— —'} />
      <Line k="Inclination" v={fleet ? `${fleet.inclination_deg.toFixed(1)}°` : '— —'} />
      <Line k="Constellation" v={fleet?.name ?? '— —'} />
    </div>
  )
}

/** What the numbers above add up to — pinned to the bottom of each column so
 *  the three read as a row of complete panels. */
function Derived({ rows }: { rows: [string, string][] }) {
  return (
    <div className="mt-auto flex flex-col gap-1.5 rounded border border-border-weak bg-bg-card-hi/60 px-3 py-2.5">
      {rows.map(([k, v]) => <Line key={k} k={k} v={v} />)}
    </div>
  )
}

function Line({ k, v }: { k: string; v: string }) {
  return (
    <span className="flex items-baseline justify-between gap-2 text-[12px]">
      <span className="uppercase tracking-[0.08em] text-text-lo">{k}</span>
      <span className="truncate font-mono tabular-nums text-text-hi">{v}</span>
    </span>
  )
}

function Column({
  title, icon, note, children,
}: { title: string; icon: React.ReactNode; note: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-col gap-3 overflow-y-auto rounded-md border border-border-weak
                    bg-bg-inset/20 p-3.5">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-[13px] uppercase tracking-[0.12em] text-text-md">{title}</span>
      </div>
      <p className="text-[12px] leading-snug text-text-faint">{note}</p>
      {children}
    </div>
  )
}
