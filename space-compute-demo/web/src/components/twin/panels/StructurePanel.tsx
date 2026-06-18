import { Section, Row } from './PopupPrimitives'
import { useDemoStore } from '../../../store/demoStore'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { deriveStats } from '../../../data/satConfigOptions'

/**
 * Sub-panel for the SpaceDcBackbone structural parts (spine, thrusters, the
 * central ADCS/tank pack, the four server racks, and the comms boom). Which
 * part was clicked is resolved upstream (TwinModulePopup) from the prim path
 * and passed as `sub`; this renders the matching static role + the satellite
 * dry mass so every backbone click lands on a meaningful card.
 */
export type StructureSub = 'spine' | 'thruster' | 'tank' | 'rack' | 'antenna'

const ROLE: Record<StructureSub, { heading: string; rows: Array<[string, string, string?]> }> = {
  spine:    { heading: 'Backbone spine',  rows: [['Role', 'Primary truss'], ['Carries', '12 server bays']] },
  thruster: { heading: 'Propulsion',      rows: [['Type', 'Bipropellant'], ['Use', 'Orbit / station-keep']] },
  tank:     { heading: 'ADCS · tank',     rows: [['Role', 'Reaction wheels'], ['Plus', 'Propellant store']] },
  rack:     { heading: 'Server rack',     rows: [['Bays', '3 blades'], ['Role', 'Compute mount']] },
  antenna:  { heading: 'Comms boom',      rows: [['Role', 'TT&C antenna'], ['Band', 'S-band']] },
}

export function StructurePanel({ sub }: { sub: StructureSub }) {
  const cfg   = useTelemetryStore((s) => s.satConfig)
  const stats = deriveStats(cfg)
  const sat   = useDemoStore((s) => s.lastState?.satellite)
  const info  = ROLE[sub]

  return (
    <>
      <Section title={info.heading}>
        {info.rows.map(([label, value, unit]) => (
          <Row key={label} label={label} value={value} unit={unit} />
        ))}
      </Section>
      <Section title="Platform">
        <Row label="Dry mass" value={Math.round(stats.launch_mass_kg).toString()} unit="kg" />
        <Row
          label="Bay temp"
          value={sat?.temperature_c != null ? sat.temperature_c.toFixed(1) : '— —'}
          unit="°C"
        />
      </Section>
    </>
  )
}
