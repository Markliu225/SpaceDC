import type {
  BatteryMaterial,
  BatterySize,
  GpuType,
  RadiatorMaterial,
  RadiatorSize,
  SolarMaterial,
  SolarSize,
  SatelliteConfig,
} from '../types/messages'

/**
 * satConfigOptions — authoritative metadata for every reconfigurable
 * hardware variant on the satellite twin. The data tables mirror
 * docs/satellite_twin_implementation.md §3 exactly; the values here drive
 * BOTH the dropdown UI (label + sub-stats) and the Web-side delta math
 * (so the "ΔSolar / Δmass / Δpayback" tiles update instantly while
 * waiting for backend's echo).
 */

export interface GpuOption {
  id: GpuType
  label: string
  /** PFLOPS produced by one card. */
  pflops_per_card: number
  /** Card thermal design power, watts. */
  tdp_w: number
  /** Card BOM cost in USD thousands. */
  cost_k: number
  /** Tint used by both the chip badge and the USD MDL material. */
  tint: string
}

// pflops_per_card = peak dense FP8 tensor PFLOPS (datasheet, no sparsity) —
// mirrors backend state_engine._GPU_TABLE / ai_workloads.GPU_SPECS.
export const GPU_OPTIONS: GpuOption[] = [
  { id: 'H100',   label: 'H100 SXM',        pflops_per_card: 1.98, tdp_w: 700,  cost_k: 30, tint: '#4A5568' },
  { id: 'H200',   label: 'H200 SXM',        pflops_per_card: 1.98, tdp_w: 700,  cost_k: 40, tint: '#3B82F6' },
  { id: 'B200',   label: 'Blackwell B200',  pflops_per_card: 4.50, tdp_w: 1000, cost_k: 45, tint: '#0F172A' },
  { id: 'MI300X', label: 'AMD MI300X',      pflops_per_card: 2.62, tdp_w: 750,  cost_k: 28, tint: '#DC2626' },
]

export const GPU_CARDS_PER_SAT = 8

export interface SolarMaterialOption {
  id: SolarMaterial
  label: string
  short: string
  efficiency: number
  density_kg_m2: number
  tint: string
}

export const SOLAR_MATERIAL_OPTIONS: SolarMaterialOption[] = [
  { id: 'Si',         label: 'Silicon',           short: 'Si',   efficiency: 0.22, density_kg_m2: 2.5, tint: '#1E3A8A' },
  { id: 'GaAs',       label: 'Gallium Arsenide',  short: 'GaAs', efficiency: 0.32, density_kg_m2: 3.0, tint: '#4C1D95' },
  { id: 'Perovskite', label: 'Perovskite Tandem', short: 'PvT',  efficiency: 0.38, density_kg_m2: 1.8, tint: '#7C3AED' },
]

export interface SolarSizeOption {
  id: SolarSize
  label: string
  area_m2_per_panel: number
  panel_count: number
}

export const SOLAR_SIZE_OPTIONS: SolarSizeOption[] = [
  { id: 'S',  label: 'Small',       area_m2_per_panel: 4,  panel_count: 2 },
  { id: 'M',  label: 'Medium',      area_m2_per_panel: 8,  panel_count: 2 },
  { id: 'L',  label: 'Large',       area_m2_per_panel: 12, panel_count: 2 },
  { id: 'XL', label: 'Extra Large', area_m2_per_panel: 16, panel_count: 2 },
]

export interface RadiatorMaterialOption {
  id: RadiatorMaterial
  label: string
  emissivity: number
  density_kg_m2: number
  tint: string
}

export const RADIATOR_MATERIAL_OPTIONS: RadiatorMaterialOption[] = [
  { id: 'Aluminum',   label: 'Bare Aluminum',           emissivity: 0.10, density_kg_m2: 4.0, tint: '#C0C0C0' },
  { id: 'WhitePaint', label: 'White Paint',             emissivity: 0.85, density_kg_m2: 4.4, tint: '#F0F0F0' },
  { id: 'OSR',        label: 'Optical Solar Reflector', emissivity: 0.92, density_kg_m2: 4.6, tint: '#D4D4D8' },
  { id: 'Graphite',   label: 'Graphite Composite',      emissivity: 0.96, density_kg_m2: 3.6, tint: '#18181B' },
]

export interface RadiatorSizeOption {
  id: RadiatorSize
  label: string
  area_m2_per_panel: number
}

export const RADIATOR_SIZE_OPTIONS: RadiatorSizeOption[] = [
  { id: 'Compact',  label: 'Compact',  area_m2_per_panel: 1 },
  { id: 'Standard', label: 'Standard', area_m2_per_panel: 2 },
  { id: 'Wide',     label: 'Wide',     area_m2_per_panel: 4 },
]

export const RADIATOR_PANELS_PER_SAT = 2

// Battery chemistry + pack size. Mirrors backend state_engine._BATT_*_TABLE:
// effective capacity_wh = mass_kg × density_wh_kg; the chemistry's round-trip
// efficiency taxes charging.
export interface BatteryMaterialOption {
  id: BatteryMaterial
  label: string
  density_wh_kg: number
  efficiency: number
  tint: string
}

export const BATTERY_MATERIAL_OPTIONS: BatteryMaterialOption[] = [
  { id: 'LiIon',      label: 'Li-ion NMC',   density_wh_kg: 250, efficiency: 0.95, tint: '#2563EB' },
  { id: 'LiFePO4',    label: 'LiFePO4',      density_wh_kg: 160, efficiency: 0.96, tint: '#059669' },
  { id: 'LiS',        label: 'Lithium-Sulfur', density_wh_kg: 400, efficiency: 0.90, tint: '#7C3AED' },
  { id: 'SolidState', label: 'Solid-State',  density_wh_kg: 350, efficiency: 0.97, tint: '#D97706' },
]

export interface BatterySizeOption {
  id: BatterySize
  label: string
  mass_kg: number
}

export const BATTERY_SIZE_OPTIONS: BatterySizeOption[] = [
  { id: 'S',  label: 'Small',       mass_kg: 10 },
  { id: 'M',  label: 'Medium',      mass_kg: 20 },
  { id: 'L',  label: 'Large',       mass_kg: 32 },
  { id: 'XL', label: 'Extra Large', mass_kg: 60 },
]

// ---------------------------------------------------------------------------
// Lookup helpers — every component uses these instead of array.find inline.
// ---------------------------------------------------------------------------

export function gpuOption(id: GpuType): GpuOption {
  return GPU_OPTIONS.find((o) => o.id === id) ?? GPU_OPTIONS[0]
}

export function solarMaterial(id: SolarMaterial): SolarMaterialOption {
  return SOLAR_MATERIAL_OPTIONS.find((o) => o.id === id) ?? SOLAR_MATERIAL_OPTIONS[0]
}

export function solarSize(id: SolarSize): SolarSizeOption {
  return SOLAR_SIZE_OPTIONS.find((o) => o.id === id) ?? SOLAR_SIZE_OPTIONS[1]
}

export function radiatorMaterial(id: RadiatorMaterial): RadiatorMaterialOption {
  return RADIATOR_MATERIAL_OPTIONS.find((o) => o.id === id) ?? RADIATOR_MATERIAL_OPTIONS[0]
}

export function radiatorSize(id: RadiatorSize): RadiatorSizeOption {
  return RADIATOR_SIZE_OPTIONS.find((o) => o.id === id) ?? RADIATOR_SIZE_OPTIONS[1]
}

export function batteryMaterial(id: BatteryMaterial): BatteryMaterialOption {
  return BATTERY_MATERIAL_OPTIONS.find((o) => o.id === id) ?? BATTERY_MATERIAL_OPTIONS[0]
}

export function batterySize(id: BatterySize): BatterySizeOption {
  return BATTERY_SIZE_OPTIONS.find((o) => o.id === id) ?? BATTERY_SIZE_OPTIONS[2]
}

/** Effective pack capacity (Wh) = mass × energy density — mirrors backend. */
export function batteryCapacityWh(material: BatteryMaterial, size: BatterySize): number {
  return batterySize(size).mass_kg * batteryMaterial(material).density_wh_kg
}

// ---------------------------------------------------------------------------
// Derived stats — same formulas as backend's _update_placeholder_physics so
// the Web-side delta panel matches the eventual state_update echo. Areas come
// from the DEPLOYABLE GEOMETRY (twin_geometry — solar cluster count, radiator
// dims), mirroring state_engine._solar_area_m2/_radiator_area_m2; the old
// S/M/L/XL / Compact..Wide size tables are dropdown metadata only and no
// longer drive any physics-facing number.
// ---------------------------------------------------------------------------

const SOLAR_CONSTANT_W_M2 = 1361
const BUS_MASS_KG         = 300
const BUS_BASE_CAPEX_USD_M = 3.0

// Mirrors state_engine.py: one 2×2 solar cluster's active area (m²) and the
// stage scale for radiator dims.
const BACKBONE_SCALE   = 1.8
const SOLAR_CLUSTER_M2 = (0.981 * 1.45 * BACKBONE_SCALE) * (0.777 * 1.05 * BACKBONE_SCALE)

/** Geometry knobs deriveStats needs — subset of TwinGeometry. */
export interface GeometryLike {
  architecture?: string
  solar_clusters_per_side: number
  radiator_long: number
  radiator_ratio: number
}

/** Engine-default geometry — used when no live twin_geometry is available. */
export const GEOMETRY_DEFAULT: GeometryLike = {
  architecture: 'truss',
  solar_clusters_per_side: 2,
  radiator_long: 1.55,
  radiator_ratio: 2.5,
}

/** Hull architectures fly integrated panels with fixed cell area — mirrors
 *  state_engine._ARCH_FIXED_SOLAR_M2. */
const ARCH_FIXED_SOLAR_M2: Record<string, number> = { lumid: 9.5, dish: 18.0 }

/** Architectures whose solar panels are part of the hull (the wing-segment
 *  stepper does not apply). */
export function hasFixedWings(geom: GeometryLike): boolean {
  return (geom.architecture ?? 'truss') in ARCH_FIXED_SOLAR_M2
}

/** Total active solar cell area (both wings), m². */
export function solarAreaM2(geom: GeometryLike): number {
  const fixed = ARCH_FIXED_SOLAR_M2[geom.architecture ?? 'truss']
  if (fixed !== undefined) return fixed
  return geom.solar_clusters_per_side * 2 * SOLAR_CLUSTER_M2
}

/** Physical radiator panel area (2 panels, single face), m² — for mass/cost. */
export function radiatorPanelAreaM2(geom: GeometryLike): number {
  const long_m  = geom.radiator_long * BACKBONE_SCALE
  const short_m = (geom.radiator_long / Math.max(0.1, geom.radiator_ratio)) * BACKBONE_SCALE
  return 2 * long_m * short_m
}

/** Emitting radiator area (2 panels × 2 faces), m² — what the physics uses. */
export function radiatorEmitAreaM2(geom: GeometryLike): number {
  return 2 * radiatorPanelAreaM2(geom)
}

export interface DerivedStats {
  /** Solar input at sunlit, normal-incidence conditions (worst-case max). */
  solar_input_max_w: number
  /** Total launched mass for the satellite, kilograms. */
  launch_mass_kg: number
  /** Aggregate compute capability — petaFLOPS at peak. */
  compute_pflops: number
  /** All-in CAPEX per satellite, USD millions. */
  capex_usd_m: number
  /** Demo proxy for peak thermal — independent of util so we can compare configs. */
  thermal_index: number
}

export function deriveStats(
  cfg: SatelliteConfig,
  geom: GeometryLike = GEOMETRY_DEFAULT,
  gpuCount: number = GPU_CARDS_PER_SAT,
): DerivedStats {
  const gpu  = gpuOption(cfg.gpu)
  const sMat = solarMaterial(cfg.solar_material)
  const rMat = radiatorMaterial(cfg.radiator_material)

  const solarArea    = solarAreaM2(geom)
  const radPanelArea = radiatorPanelAreaM2(geom)

  const solar_input_max_w = sMat.efficiency * solarArea * SOLAR_CONSTANT_W_M2

  const compute_pflops = gpu.pflops_per_card * gpuCount

  const launch_mass_kg =
    BUS_MASS_KG
    + solarArea * sMat.density_kg_m2
    + radPanelArea * rMat.density_kg_m2

  const capex_usd_m =
    BUS_BASE_CAPEX_USD_M
    + (gpu.cost_k * gpuCount) / 1000
    + 0.05 * solarArea
    + 0.02 * radPanelArea

  // Thermal index — lower is better. Proxy: payload power / radiator capacity.
  const radiator_capacity = rMat.emissivity * radiatorEmitAreaM2(geom)
  const thermal_index = (gpu.tdp_w * gpuCount) / Math.max(0.05, radiator_capacity)

  return {
    solar_input_max_w,
    launch_mass_kg,
    compute_pflops,
    capex_usd_m,
    thermal_index,
  }
}
