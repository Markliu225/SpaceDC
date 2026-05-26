import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { useBackendBridge } from '../hooks/useBackendBridge'
import { EarthViewport } from '../components/overview/EarthViewport'
import { NetworkOverview } from '../components/overview/NetworkOverview'
import { SatelliteList } from '../components/overview/SatelliteList'
import { RealCoverageMap } from '../components/overview/RealCoverageMap'
import { SatelliteDetail } from '../components/overview/SatelliteDetail'
import { SystemHealth } from '../components/overview/SystemHealth'
import { EventLog } from '../components/overview/EventLog'
import { CostPanel } from '../components/overview/CostPanel'

/**
 * OverviewPage — single-viewport mission control. Targets 1440×900.
 *
 * AppShell adds 44 (header) + 24 (padding) → usable 832px.
 *
 *  ┌───────────────────────────────────────────────────────────────┐
 *  │ NetworkOverview (KPI x 4)                                 74px│
 *  ├──────────────────────────────┬───────────────┬────────────────┤
 *  │                              │ SatelliteList │ RealCoverageMap│
 *  │ EarthViewport          1fr   │   col-3       │   col-3        │
 *  │   col-6                      │               │                │
 *  ├──────────────────────────────┴───────────────┴────────────────┤
 *  │ SatelliteDetail (full width)                             188px│
 *  ├──────────────────┬──────────────────────┬──────────────────────┤
 *  │ SystemHealth     │ EventLog             │ CostPanel        144 │
 *  │   col-3          │   col-4              │   col-5              │
 *  └──────────────────┴──────────────────────┴──────────────────────┘
 *
 * Tracks: 74 / 1fr / 188 / 144. Old layout's LinkAndTraffic,
 * SatelliteStatus donut, SelectedSatellite (legacy 24-sat), CoverageMap
 * (decorative swath), and UpcomingEvents panels are dropped — their roles
 * are covered by SatelliteList (status groups) + RealCoverageMap (real
 * sub-sat footprints) + SatelliteDetail (any-sat 14-param read).
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

      <div className="col-span-6 min-h-0 overflow-hidden">
        <EarthViewport />
      </div>
      <div className="col-span-3 min-h-0 overflow-hidden">
        <SatelliteList />
      </div>
      <div className="col-span-3 min-h-0 overflow-hidden">
        <RealCoverageMap />
      </div>

      <div className="col-span-12 min-h-0 overflow-hidden">
        <SatelliteDetail />
      </div>

      <div className="col-span-3 min-h-0 overflow-hidden">
        <SystemHealth />
      </div>
      <div className="col-span-4 min-h-0 overflow-hidden">
        <EventLog />
      </div>
      <div className="col-span-5 min-h-0 overflow-hidden">
        <CostPanel />
      </div>
    </div>
  )
}
