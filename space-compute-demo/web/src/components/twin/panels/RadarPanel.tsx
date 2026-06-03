import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'

// Static radar specs — the SatelliteState model doesn't carry these (the
// demo's "radar" is a representational dish, not a parameterised payload).
// Pulled into a local constant so a future RadarConfig type can take over
// without rewriting this panel.
const RADAR_SPECS = {
  band: 'X-band',
  bandRange: '8–12 GHz',
  tx_kW: 2.5,
  gain_dBi: 38,
}

/** Sub-panel for the radar / comms payload. Live rows are downlink rate
 * (state.satellite.downlink_mbps; bimodal 0 or ~120 in the current
 * physics) and ground-station id (state.mission.ground_id during a
 * mission, falls back to the default GS the first ground pass uses). */
export function RadarPanel() {
  const sat     = useDemoStore((s) => s.lastState?.satellite)
  const mission = useDemoStore((s) => s.lastState?.mission)

  const dl  = sat?.downlink_mbps ?? 0
  const linked = dl > 0
  const gs = mission?.ground_id && mission.ground_id !== '' ? mission.ground_id : 'GS-SVALBARD'

  return (
    <>
      <Section title="Antenna">
        <Row label="Band"      value={RADAR_SPECS.band} unit={RADAR_SPECS.bandRange} />
        <Row label="Peak TX"   value={RADAR_SPECS.tx_kW.toFixed(1)} unit="kW" />
        <Row label="Gain"      value={RADAR_SPECS.gain_dBi.toString()} unit="dBi" />
      </Section>
      <Section title="Downlink">
        <Row label="Rate"      value={dl > 0 ? dl.toFixed(0) : '0'} unit="Mb/s" />
        <Row
          label="Link"
          value={linked ? '◉ LOCKED' : '○ NO AOS'}
          tone={linked ? 'accent' : undefined}
        />
        <Row label="GS"        value={gs} />
      </Section>
    </>
  )
}
