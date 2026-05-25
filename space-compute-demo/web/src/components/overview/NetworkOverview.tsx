import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Card, Num } from '../primitives'

/**
 * NetworkOverview — 4 KPI tiles, each its own <Card> in a sub-grid.
 * Differs from a vanilla Metric grid because each KPI has bespoke
 * sub-text formatting:
 *   - Active Links: inline breakdown "(32 ISL / 6 GSL)"
 *   - Coverage: trailing "%" rendered as superscript
 *   - Throughput: muted "Mbps" trailing unit
 *   - Total Satellites: "Online" sub-text in text.lo
 */
export function NetworkOverview() {
  const net = useTelemetryStore((s) => s.network)
  return (
    <div className="grid grid-cols-4 gap-3">
      <Card dense>
        <Label>Total Satellites</Label>
        <div className="mt-2 flex items-baseline">
          <Num value={net.total} className="text-[30px] leading-none font-semibold text-text-hi" />
        </div>
        <div className="mt-2 text-[12px] text-text-lo">
          <span className="text-ok">●</span>{' '}
          <Num value={net.online} className="text-text-md" /> Online
        </div>
      </Card>

      <Card dense>
        <Label>Active Links</Label>
        <div className="mt-2 flex items-baseline gap-2">
          <Num value={net.links_total} className="text-[30px] leading-none font-semibold text-text-hi" />
          <span className="text-[12px] text-text-lo tabular">
            ({net.isl_links} ISL / {net.gsl_links} GSL)
          </span>
        </div>
        <div className="mt-2 text-[12px] text-text-lo">cross-link mesh</div>
      </Card>

      <Card dense>
        <Label>Coverage</Label>
        <div className="mt-2 flex items-baseline">
          <Num value={net.coverage_pct} digits={0} className="text-[30px] leading-none font-semibold text-text-hi" />
          <span className="ml-0.5 text-[13px] text-text-md self-start mt-0.5">%</span>
        </div>
        <div className="mt-2 text-[12px] text-text-lo">global land + sea</div>
      </Card>

      <Card dense>
        <Label>Agg. Throughput</Label>
        <div className="mt-2 flex items-baseline">
          <Num value={net.agg_throughput_mbps} className="text-[30px] leading-none font-semibold text-text-hi" />
          <span className="ml-1 text-[13px] text-text-md">Mbps</span>
        </div>
        <div className="mt-2 text-[12px] text-text-lo">downlink aggregate</div>
      </Card>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] uppercase tracking-[0.10em] text-text-md">
      {children}
    </div>
  )
}
