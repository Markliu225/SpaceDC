import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { useBackendBridge } from '../hooks/useBackendBridge'
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
 * OverviewPage — single-viewport mission control. Targets 1440×900.
 *
 * AppShell adds 44 (header) + 24 (padding) → usable 832px.
 *
 *  ┌───────────────────────────────────────────────────────────────┐
 *  │ NetworkOverview (KPI x 4)                                 74px│
 *  ├──────────────────────────────┬────────────────────────────────┤
 *  │                              │ SatelliteStatus           1fr  │
 *  │ Earth Viewport          1fr  ├────────────────────────────────┤
 *  │                              │ LinkAndTraffic            1fr  │
 *  ├──────────────────────────────┴────────────────────────────────┤
 *  │ SelectedSatellite (full width, 3-col interior)           188px│
 *  ├──────────┬─────────────┬─────────────┬─────────────────────────┤
 *  │ SysHealth│ EventLog    │ CoverageMap │ Upcoming           144 │
 *  │   col-3  │   col-4     │   col-3     │   col-2                │
 *  └──────────┴─────────────┴─────────────┴─────────────────────────┘
 *
 * Tracks: 74 / 1fr / 188 / 144. Fixed = 406 + 30 (gaps) = 436. Row 2 (Earth)
 * gets 396 → right rail / 2 = ~190 each. Donut + 4 legend rows fit, both
 * sparklines fit. Row 4 distributes the 4 smaller panels horizontally.
 */
export function OverviewPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera)
  const connected    = useDemoStore((s) => s.connected)
  useEffect(() => {
    if (connected) changeCamera('overview')
  }, [connected, changeCamera])
  useMockTelemetryFeed()
  useBackendBridge()

  return (
    <div
      className="grid w-full bg-bg-app font-sans text-text-md gap-2.5 overflow-hidden"
      style={{
        height: 'calc(100vh - 44px - 24px - 4px)',
        gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
        gridTemplateRows: '74px minmax(0, 1fr) 188px 144px',
      }}
    >
      {/* overflow-visible so the Constellation selector's dropdown can
          extend BELOW this row without getting clipped. The KPI tiles
          inside NetworkOverview are still fixed at 74px so the row's
          visible footprint doesn't change. */}
      <div className="col-span-12 min-h-0 overflow-visible relative z-30">
        <NetworkOverview />
      </div>

      <div className="col-span-7 min-h-0 overflow-hidden">
        <EarthViewport />
      </div>
      <div
        className="col-span-5 grid min-h-0 gap-2.5 overflow-hidden"
        style={{ gridTemplateRows: 'minmax(0, 1fr) minmax(0, 1fr)' }}
      >
        <div className="min-h-0 overflow-hidden"><SatelliteStatus /></div>
        <div className="min-h-0 overflow-hidden"><LinkAndTraffic /></div>
      </div>

      <div className="col-span-12 min-h-0 overflow-hidden">
        <SelectedSatellite />
      </div>

      <div className="col-span-3 min-h-0 overflow-hidden">
        <SystemHealth />
      </div>
      <div className="col-span-4 min-h-0 overflow-hidden">
        <EventLog />
      </div>
      <div className="col-span-3 min-h-0 overflow-hidden">
        <CoverageMap />
      </div>
      <div className="col-span-2 min-h-0 overflow-hidden">
        <UpcomingEvents />
      </div>
    </div>
  )
}
