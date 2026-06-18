import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { radiatorMaterial } from '../../../data/satConfigOptions'

/**
 * Sub-panel for one of the two dedicated radiator panels (±Z booms off the
 * spine). Area comes from the LIVE deployable geometry (Feature 3/4): total =
 * 2 panels × 2 faces, so resizing the radiator changes the area and the heat
 * it rejects (Stefan-Boltzmann ε·σ·A·(T⁴−T_bg⁴)) in real time. ε is the chosen
 * coating material.
 */
export function RadiatorPanel({ which }: { which: 'Top' | 'Bot' }) {
  const sat  = useDemoStore((s) => s.lastState?.satellite)
  const geom = useDemoStore((s) => s.lastState?.twin_geometry)
  const cfg  = useTelemetryStore((s) => s.satConfig)
  const rMat = radiatorMaterial(cfg.radiator_material)

  const totalArea = sat?.radiator_area_m2              // both panels, both faces
  const panelArea = totalArea != null ? totalArea / 2 : null   // this panel (2 faces)
  const radW      = sat?.radiator_power_w
  const shareW    = radW != null ? radW / 2 : null
  const tempC     = sat?.temperature_c
  const ratio     = geom?.radiator_ratio

  const label = which === 'Top' ? '+Z radiator' : '−Z radiator'

  return (
    <>
      <Section title={label}>
        <Row label="Material"   value={rMat.label} />
        <Row label="This panel" value={panelArea != null ? panelArea.toFixed(1) : '— —'} unit="m²" />
        <Row label="Ratio"      value={ratio != null ? `1:${ratio.toFixed(1)}` : '— —'} />
        <Row label="ε"          value={rMat.emissivity.toFixed(2)} />
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
