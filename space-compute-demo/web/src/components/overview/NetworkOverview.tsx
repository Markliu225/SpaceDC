import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Num } from '../primitives'

/**
 * NetworkOverview — 4 dense KPI tiles, designed for a fixed 84px row.
 */
export function NetworkOverview() {
  const net = useTelemetryStore((s) => s.network)
  return (
    <div className="grid h-full grid-cols-4 gap-3">
      <Tile label="Total Satellites">
        <div className="flex items-baseline gap-2">
          <Num value={net.total} className="text-[26px] leading-none font-semibold text-text-hi" />
          <span className="text-[11px] text-ok">●&nbsp;{net.online} online</span>
        </div>
        <Sub>orbital constellation</Sub>
      </Tile>

      <Tile label="Active Links">
        <div className="flex items-baseline gap-2">
          <Num value={net.links_total} className="text-[26px] leading-none font-semibold text-text-hi" />
          <span className="text-[11px] text-text-lo tabular">{net.isl_links} ISL / {net.gsl_links} GSL</span>
        </div>
        <Sub>cross-link mesh</Sub>
      </Tile>

      <Tile label="Coverage">
        <div className="flex items-baseline">
          <Num value={net.coverage_pct} digits={0} className="text-[26px] leading-none font-semibold text-text-hi" />
          <span className="ml-1 text-[12px] text-text-md">%</span>
        </div>
        <Sub>global land + sea</Sub>
      </Tile>

      <Tile label="Agg. Throughput">
        <div className="flex items-baseline">
          <Num value={net.agg_throughput_mbps} className="text-[26px] leading-none font-semibold text-text-hi" />
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
