import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { EarthViewport } from '../components/overview/EarthViewport'
import { NetworkOverview } from '../components/overview/NetworkOverview'
import { SatelliteStatus } from '../components/overview/SatelliteStatus'
import { LinkAndTraffic } from '../components/overview/LinkAndTraffic'
import { SystemHealth } from '../components/overview/SystemHealth'
import { CoverageMap } from '../components/overview/CoverageMap'
import { EventLog } from '../components/overview/EventLog'
import { SelectedSatellite } from '../components/overview/SelectedSatellite'
import { UpcomingEvents } from '../components/overview/UpcomingEvents'

/**
 * OverviewPage — single-viewport mission control. No scroll. 1440×900 target.
 *
 * AppShell header is 44px; .shell__main has 12px padding both sides → usable
 * area is calc(100vh - 68px). The page is a 12-col CSS grid with explicit
 * row tracks so all 8 panels fit on screen.
 *
 *  ┌───────────────────────────────────────────────────────────────┐
 *  │ KPI x 4                                                  84px │
 *  ├──────────────────────────────┬────────────────────────────────┤
 *  │ Earth Viewport               │ SatelliteStatus                │
 *  │ (centerpiece)                ├────────────────────────────────┤
 *  │                          1fr │ LinkAndTraffic           1fr   │
 *  │                              ├────────────────────────────────┤
 *  │                              │ SystemHealth                   │
 *  ├──────────────────────────────┴────────────────────────────────┤
 *  │ SelectedSatellite (col-7)            │ CoverageMap (col-5)180 │
 *  ├──────────────────────────────────────┼─────────────┬──────────┤
 *  │ EventLog (col-7)                     │ Upcoming Events  150px │
 *  └──────────────────────────────────────┴────────────────────────┘
 */
export function OverviewPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera)
  const connected    = useDemoStore((s) => s.connected)
  useEffect(() => {
    if (connected) changeCamera('overview')
  }, [connected, changeCamera])
  useMockTelemetryFeed()

  return (
    <div
      className="grid w-full bg-bg-app px-3 py-3 font-sans text-text-md gap-3"
      style={{
        height: 'calc(100vh - 44px - 24px)', // shell header 44 + .shell__main padding 12x2
        gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
        gridTemplateRows: '84px minmax(0, 1fr) 180px 140px',
      }}
    >
      {/* Row 1: KPI strip */}
      <div className="col-span-12 min-h-0">
        <NetworkOverview />
      </div>

      {/* Row 2: viewport + right rail (sat status / traffic / health) */}
      <div className="col-span-7 min-h-0">
        <EarthViewport />
      </div>
      <div className="col-span-5 grid min-h-0 gap-3" style={{ gridTemplateRows: '1fr 1fr 1fr' }}>
        <div className="min-h-0"><SatelliteStatus /></div>
        <div className="min-h-0"><LinkAndTraffic /></div>
        <div className="min-h-0"><SystemHealth /></div>
      </div>

      {/* Row 3: selected sat + coverage */}
      <div className="col-span-7 min-h-0">
        <SelectedSatellite />
      </div>
      <div className="col-span-5 min-h-0">
        <CoverageMap />
      </div>

      {/* Row 4: event log + upcoming */}
      <div className="col-span-7 min-h-0">
        <EventLog />
      </div>
      <div className="col-span-5 min-h-0">
        <UpcomingEvents />
      </div>
    </div>
  )
}
