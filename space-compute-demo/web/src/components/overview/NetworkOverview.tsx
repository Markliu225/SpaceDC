import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Num } from '../primitives'
import { ConstellationSelector } from './ConstellationSelector'

/**
 * NetworkOverview — 5-tile top strip:
 *   [ Constellation selector | Total Sats | Active Links | Coverage | Throughput ]
 *
 * All KPI values read from useTelemetryStore.fleet which is mirrored from
 * the backend's /state.constellation snapshot via useBackendBridge.
 */
export function NetworkOverview() {
  const fleet = useTelemetryStore((s) => s.fleet)

  return (
    <div className="grid h-full grid-cols-5 gap-3">
      <ConstellationSelector />

      <Tile label="Total Satellites">
        <div className="flex items-baseline gap-2">
          <Num value={fleet?.total ?? 0} className="text-[26px] leading-none font-semibold text-text-hi" />
          <span className="text-[11px] text-ok">
            ●&nbsp;<Num value={fleet?.online ?? 0} className="text-ok" /> online
          </span>
        </div>
        <Sub>{fleet?.eclipse != null ? <><Num value={fleet.eclipse} className="text-info" /> eclipse · <Num value={fleet.standby} className="text-warn" /> standby · <Num value={fleet.offline} className="text-err" /> offline</> : 'awaiting backend…'}</Sub>
      </Tile>

      <Tile label="Active Links">
        <div className="flex items-baseline gap-2">
          <Num value={fleet?.links_total ?? 0} className="text-[26px] leading-none font-semibold text-text-hi" />
          <span className="text-[11px] text-text-lo tabular">
            <Num value={fleet?.isl_links ?? 0} className="text-text-md" /> ISL / <Num value={fleet?.gsl_links ?? 0} className="text-text-md" /> GSL
          </span>
        </div>
        <Sub>cross-link mesh</Sub>
      </Tile>

      <Tile label="Coverage">
        <div className="flex items-baseline">
          <Num value={fleet?.coverage_pct ?? 0} digits={0} className="text-[26px] leading-none font-semibold text-text-hi" />
          <span className="ml-1 text-[12px] text-text-md">%</span>
        </div>
        <Sub>global land + sea</Sub>
      </Tile>

      <Tile label="Agg. Throughput">
        <div className="flex items-baseline">
          <Num value={fleet?.agg_throughput_mbps ?? 0} digits={0} className="text-[26px] leading-none font-semibold text-text-hi" />
          <span className="ml-1 text-[12px] text-text-md">Mbps</span>
        </div>
        <Sub>downlink aggregate</Sub>
      </Tile>
    </div>
  )
}

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card dense className="flex flex-col justify-center min-h-0">
      <div className="text-[10px] uppercase tracking-[0.10em] text-text-md">{label}</div>
      <div className="mt-1">{children}</div>
    </Card>
  )
}

function Sub({ children }: { children: React.ReactNode }) {
  return <div className="mt-0.5 text-[11px] text-text-lo">{children}</div>
}
