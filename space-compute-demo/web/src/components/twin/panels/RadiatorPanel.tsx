import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { radiatorMaterial } from '../../../data/satConfigOptions'

/**
 * Sub-panel for one of the two dedicated radiator panels (±Z booms off the
 * spine). The current twin model authors each radiator as a single 2:5 panel
 * (~1.12 × 2.79 m) standing perpendicular to the solar wings; both faces
 * radiate. Static rows show the panel geometry + material; the Live section
 * pulls the backend's emitted power (split across the two radiators) and the
 * bay temperature it is rejecting.
 */
// Authored radiator face (tools/gen_twin_satellite.py: 111.6 × 279 cm on stage).
const RAD_FACE_M2 = 1.116 * 2.79          // ≈ 3.11 m² one side
const RAD_BOTH_M2 = RAD_FACE_M2 * 2       // both faces radiate to deep space

export function RadiatorPanel({ which }: { which: 'Top' | 'Bot' }) {
  const sat  = useDemoStore((s) => s.lastState?.satellite)
  const cfg  = useTelemetryStore((s) => s.satConfig)
  const rMat = radiatorMaterial(cfg.radiator_material)

  const tempC  = sat?.temperature_c
  const radW   = sat?.radiator_power_w            // total emit across both panels
  const shareW = radW != null ? radW / 2 : null   // this panel's half

  const label = which === 'Top' ? '+Z radiator' : '−Z radiator'

  return (
    <>
      <Section title={label}>
        <Row label="Material"  value={rMat.label} />
        <Row label="Face area" value={RAD_FACE_M2.toFixed(2)} unit="m²" />
        <Row label="Both sides" value={RAD_BOTH_M2.toFixed(2)} unit="m²" />
        <Row label="ε"         value={rMat.emissivity.toFixed(2)} />
      </Section>
      <Section title="Live">
        <Row
          label="Bay temp"
          value={tempC != null ? tempC.toFixed(1) : '— —'}
          unit="°C"
          tone={tempC != null && tempC > 60 ? 'hot' : undefined}
        />
        <Row
          label="Emitting (this)"
          value={shareW != null ? shareW.toFixed(0) : '— —'}
          unit="W"
          tone={shareW != null && shareW > 0 ? 'accent' : undefined}
        />
        <Row
          label="Emitting (total)"
          value={radW != null ? radW.toFixed(0) : '— —'}
          unit="W"
        />
      </Section>
    </>
  )
}
