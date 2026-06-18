import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import {
  solarMaterial, solarSize,
} from '../../../data/satConfigOptions'

/** Sub-panel for one of the deployed solar wings — same model + material
 * per the user's spec (panels are symmetric). Shows the static config
 * (material, size, area, efficiency, peak rating) alongside the live
 * solar-input power so the user can see how the chosen panel size is
 * generating right now. */
export function SolarPanel({ wing }: { wing: 'Pos' | 'Neg' }) {
  const sat = useDemoStore((s) => s.lastState?.satellite)
  const cfg = useTelemetryStore((s) => s.satConfig)
  const mat  = solarMaterial(cfg.solar_material)
  const size = solarSize(cfg.solar_size)
  const areaPerPanel = size.area_m2_per_panel
  const totalArea    = areaPerPanel * size.panel_count
  const peakW        = mat.efficiency * areaPerPanel * 1361   // per-panel peak
  const fleetPeakW   = peakW * size.panel_count
  // Live live in_w from backend (sum across panels); show this panel's share.
  const liveTotalW = sat?.solar_input_w
  const liveShareW = liveTotalW != null ? liveTotalW / Math.max(1, size.panel_count) : null
  const sunlit = sat?.sunlit

  const sideLabel = wing === 'Pos' ? '+Y wing' : '−Y wing'

  return (
    <>
      <Section title={sideLabel}>
        <Row label="Material" value={mat.label} />
        <Row label="Size"     value={`${size.label} · ${areaPerPanel} m²`} />
        <Row label="η"        value={(mat.efficiency * 100).toFixed(0)} unit="%" />
      </Section>
      <Section title={`Array · ${size.panel_count}×`}>
        <Row label="Total area" value={totalArea.toFixed(1)} unit="m²" />
        <Row label="Peak rating" value={Math.round(fleetPeakW).toString()} unit="W" />
      </Section>
      <Section title="Live">
        <Row
          label={sunlit ? 'Sunlit' : 'Eclipse'}
          value={sunlit ? '◉' : '○'}
          tone={sunlit ? 'accent' : 'hot'}
        />
        <Row
          label="Generating"
          value={liveTotalW != null ? Math.round(liveTotalW).toString() : '— —'}
          unit="W"
          tone={liveTotalW != null && liveTotalW > 0 ? 'accent' : undefined}
        />
        <Row
          label="This panel"
          value={liveShareW != null ? Math.round(liveShareW).toString() : '— —'}
          unit="W"
        />
      </Section>
    </>
  )
}
