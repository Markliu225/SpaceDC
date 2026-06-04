import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import {
  radiatorMaterial, solarSize, deriveStats,
} from '../../../data/satConfigOptions'

/** Sub-panel for the payload bay shell (载荷舱壳). Now physics-driven:
 * power balance + battery integration + Stefan-Boltzmann radiator + standing
 * alarms come straight from the backend StateEngine — no synthetic
 * sinusoids. Per the user's spec the radiator shares the solar panel's
 * area (the panel back IS the radiator), so the displayed area pulls from
 * solar_size.area × panel_count rather than the legacy radiator_size. */

const ALARM_LABEL: Record<string, { label: string; tone: 'warn' | 'hot' }> = {
  low_battery:        { label: 'Low battery',          tone: 'hot' },
  overtemp:           { label: 'Over-temperature',     tone: 'hot' },
  undertemp:          { label: 'Under-temperature',    tone: 'warn' },
  eclipse_deficit:    { label: 'Eclipse — power deficit', tone: 'hot' },
  radiator_undersized:{ label: 'Radiator undersized',  tone: 'warn' },
  solar_undersized:   { label: 'Solar undersized',     tone: 'warn' },
}

export function ShellPanel() {
  const sat   = useDemoStore((s) => s.lastState?.satellite)
  const cfg   = useTelemetryStore((s) => s.satConfig)
  const rMat  = radiatorMaterial(cfg.radiator_material)
  const sSize = solarSize(cfg.solar_size)
  const stats = deriveStats(cfg)
  const panelArea = sSize.area_m2_per_panel * sSize.panel_count   // = radiator area

  const tempC = sat?.temperature_c
  const soc   = sat?.battery_soc
  const capWh = sat?.battery_capacity_wh
  const chgW  = sat?.battery_charge_w
  const radW  = sat?.radiator_power_w
  const alarms = sat?.alarms ?? []

  return (
    <>
      <Section title="Battery">
        <Row
          label="SOC"
          value={soc != null ? Math.round(soc * 100).toString() : '— —'}
          unit="%"
          tone={soc != null && soc < 0.20 ? 'hot' : undefined}
        />
        <Row label="Capacity"
             value={capWh != null ? Math.round(capWh).toString() : '— —'} unit="Wh" />
        <Row
          label={chgW != null && chgW < 0 ? 'Discharge' : 'Charge'}
          value={chgW != null ? Math.abs(chgW).toFixed(0) : '— —'}
          unit="W"
          tone={chgW != null && chgW < 0 ? 'warn' : 'accent'}
        />
      </Section>
      <Section title="Thermal">
        <Row label="Bay temp"
             value={tempC != null ? tempC.toFixed(1) : '— —'} unit="°C"
             tone={tempC != null && tempC > 60 ? 'hot' : undefined} />
        <Row label="Radiator"  value={`${rMat.label}`} />
        <Row label="Area (back of panel)" value={panelArea.toFixed(1)} unit="m²" />
        <Row label="ε"         value={rMat.emissivity.toFixed(2)} />
        <Row label="Emitting"  value={radW != null ? radW.toFixed(0) : '— —'} unit="W" />
      </Section>
      <Section title="Structure">
        <Row label="Dry mass"  value={Math.round(stats.launch_mass_kg).toString()} unit="kg" />
      </Section>
      <Section title="Design check">
        {(() => {
          const sd = sat?.solar_demand_avg_w
          const ss = sat?.solar_supply_avg_w
          const td = sat?.thermal_peak_demand_w
          const tm = sat?.thermal_max_emit_w
          const solarMargin   = (ss != null && sd != null) ? ss - sd : null
          const thermalMargin = (tm != null && td != null) ? tm - td : null
          return (
            <>
              <Row label="Solar avg demand"
                   value={sd != null ? Math.round(sd).toString() : '— —'} unit="W" />
              <Row label="Solar avg supply"
                   value={ss != null ? Math.round(ss).toString() : '— —'} unit="W"
                   tone={solarMargin != null && solarMargin < 0 ? 'hot' : 'accent'} />
              <Row label="Thermal peak demand"
                   value={td != null ? Math.round(td).toString() : '— —'} unit="W" />
              <Row label="Thermal max emit"
                   value={tm != null ? Math.round(tm).toString() : '— —'} unit="W"
                   tone={thermalMargin != null && thermalMargin < 0 ? 'hot' : 'accent'} />
            </>
          )
        })()}
      </Section>
      {alarms.length > 0 ? (
        <Section title="Alarms">
          {alarms.map((a) => {
            const entry = ALARM_LABEL[a] ?? { label: a, tone: 'warn' as const }
            return (
              <Row
                key={a}
                label={entry.tone === 'hot' ? '◉ ALERT' : '◉ WARN'}
                value={entry.label}
                tone={entry.tone}
              />
            )
          })}
        </Section>
      ) : null}
    </>
  )
}
