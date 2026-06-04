import { Cpu, Snowflake, Sun } from 'lucide-react'
import { Card } from '../primitives'
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

      <DesignSummary />
    </Card>
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
