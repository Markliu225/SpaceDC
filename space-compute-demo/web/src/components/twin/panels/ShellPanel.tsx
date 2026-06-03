import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import {
  radiatorMaterial, radiatorSize, deriveStats, RADIATOR_PANELS_PER_SAT,
} from '../../../data/satConfigOptions'

/** Sub-panel for the payload bay shell (载荷舱壳). Pulls live temperature
 * and SOC from the backend state when available, and falls back to dashes
 * before the first WS update lands. The static rows (radiator family /
 * area / emissivity / dry mass) come straight from the Configurator's
 * satConfig + the option tables. */
export function ShellPanel() {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const cfg = useTelemetryStore((s) => s.satConfig)
  const rMat = radiatorMaterial(cfg.radiator_material)
  const rSz  = radiatorSize(cfg.radiator_size)
  const stats = deriveStats(cfg)
  const radArea = RADIATOR_PANELS_PER_SAT * rSz.area_m2_per_panel

  const tempC = sat?.temperature_c
  const soc   = sat?.battery_soc

  return (
    <>
      <Section title="Live">
        <Row label="Bay Temp"  value={tempC != null ? tempC.toFixed(1) : '— —'} unit="°C" />
        <Row label="Battery"   value={soc   != null ? Math.round(soc * 100).toString() : '— —'} unit="%" />
      </Section>
      <Section title="Thermal config">
        <Row label="Radiator"  value={`${rMat.label} · ${rSz.label}`} />
        <Row label="Area"      value={radArea.toFixed(1)}   unit="m²" />
        <Row label="Emissivity" value={rMat.emissivity.toFixed(2)} unit="ε" />
      </Section>
      <Section title="Structure">
        <Row label="Dry mass"  value={Math.round(stats.launch_mass_kg).toString()} unit="kg" />
      </Section>
    </>
  )
}
