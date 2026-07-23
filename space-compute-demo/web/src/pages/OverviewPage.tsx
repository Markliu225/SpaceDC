import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { useBackendBridge } from '../hooks/useBackendBridge'
import { EarthViewport } from '../components/overview/EarthViewport'
import { NetworkOverview } from '../components/overview/NetworkOverview'
import { OrbitDesignerPanel } from '../components/overview/OrbitDesignerPanel'
import { SatelliteDetail } from '../components/overview/SatelliteDetail'
import { EventLog } from '../components/overview/EventLog'
import { CostPanel } from '../components/overview/CostPanel'

/**
 * OverviewPage — single-viewport mission control. Targets 1440×900.
 *
 * AppShell adds 44 (header) + 24 (padding) → usable 832px.
 *
 *  ┌───────────────────────────────────────────────────────────────┐
 *  │ NetworkOverview (KPI x 4)                                 74px│
 *  ├──────────────────────────────────────────────┬────────────────┤
 *  │                                              │ ConstellationS.│
 *  │ EarthViewport                          1fr   │   col-3        │
 *  │   col-9                                      │                │
 *  ├──────────────────────────────────────────────┴────────────────┤
 *  │ SatelliteDetail (incl. sat dropdown in header)           120px│
 *  ├────────────────┬────────────────────────────────────────────────┤
 *  │ EventLog       │ CostPanel                                  144 │
 *  │   col-4        │   col-8 (4 × 2 = 8 metric tiles, full labels)  │
 *  └────────────────┴────────────────────────────────────────────────┘
 *
 * Tracks: 74 / 1fr / 120 / 144. Row 3 trimmed by 24px to grow the
 * Omniverse viewport vertically; Detail's chip-wrap + 3-up bar layout
 * fits in the shorter height since DOWNLINK / GPU UTIL / BATTERY / TEMP
 * no longer share the param grid with the bars.
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
        gridTemplateRows: '74px minmax(0, 1fr) 120px 144px',
      }}
    >
      {/* overflow-visible so the Constellation selector's dropdown can
          extend BELOW this row without getting clipped. The KPI tiles
          inside NetworkOverview are still fixed at 74px so the row's
          visible footprint doesn't change. */}
      <div className="col-span-12 min-h-0 overflow-visible relative z-30">
        <NetworkOverview />
      </div>

      <div className="col-span-9 min-h-0 overflow-hidden">
        <EarthViewport />
      </div>
      {/* Right column — Orbit Designer (six elements + Walker + Singapore
          ground-station visibility) with the coverage map as its second tab. */}
      <div className="col-span-3 min-h-0 overflow-hidden">
        <OrbitDesignerPanel />
      </div>

      {/* overflow-visible + z-30: the satellite selector dropdown inside
          SatelliteDetail needs to overflow into row 4 (EventLog / CostPanel)
          without being clipped by either this wrapper or the row below. */}
      <div className="col-span-12 min-h-0 overflow-visible relative z-30">
        <SatelliteDetail />
      </div>

      <div className="col-span-4 min-h-0 overflow-hidden">
        <EventLog />
      </div>
      <div className="col-span-8 min-h-0 overflow-hidden">
        <CostPanel />
      </div>
    </div>
  )
}
