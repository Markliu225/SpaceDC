import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { solarMaterial } from '../../../data/satConfigOptions'

/** Sub-panel for one of the deployed solar wings. Area + count come from the
 * LIVE deployable geometry (Feature 3/4): total area = clusters/side × 2 sides,
 * so adding panels changes these numbers and the generated power in real time.
 * η is the chosen cell material; the live solar input is the backend's
 * η·area·flux·incidence. */
export function SolarPanel({ wing }: { wing: 'Pos' | 'Neg' }) {
  const sat  = useDemoStore((s) => s.lastState?.satellite)
  const geom = useDemoStore((s) => s.lastState?.twin_geometry)
  const cfg  = useTelemetryStore((s) => s.satConfig)
  const mat  = solarMaterial(cfg.solar_material)

  const totalArea  = sat?.solar_area_m2                 // live, geometry-driven
  const clusters   = geom?.solar_clusters_per_side
  const peakW      = totalArea != null ? mat.efficiency * totalArea * 1361 : null
  const liveTotalW = sat?.solar_input_w
  const liveShareW = liveTotalW != null ? liveTotalW / 2 : null   // per wing
  const sunlit     = sat?.sunlit

  const sideLabel = wing === 'Pos' ? '+Y wing' : '−Y wing'

  return (
    <>
      <Section title={sideLabel}>
        <Row label="Material" value={mat.label} />
        <Row label="η"        value={(mat.efficiency * 100).toFixed(0)} unit="%" />
        <Row label="Clusters" value={clusters != null ? `${clusters} × 2 sides` : '— —'} />
      </Section>
      <Section title="Array (both wings)">
        <Row label="Total area"  value={totalArea != null ? totalArea.toFixed(1) : '— —'} unit="m²" />
        <Row label="Peak rating" value={peakW != null ? Math.round(peakW).toString() : '— —'} unit="W" />
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
          label="This wing"
          value={liveShareW != null ? Math.round(liveShareW).toString() : '— —'}
          unit="W"
        />
      </Section>
    </>
  )
}
