import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { useBackendBridge } from '../hooks/useBackendBridge'
import { EarthViewport } from '../components/overview/EarthViewport'
import { NetworkOverview } from '../components/overview/NetworkOverview'
import { OrbitDesignerPanel } from '../components/overview/OrbitDesignerPanel'
import { SatelliteDetail } from '../components/overview/SatelliteDetail'

/**
 * OverviewPage — single-viewport mission control. Targets 1440×900.
 *
 * AppShell adds 44 (header) + 24 (padding) → usable 832px.
 *
 *  ┌───────────────────────────────────────────────────────────────┐
 *  │ NetworkOverview (KPI x 4)                                 74px│
 *  ├──────────────────────────────────────────────┬────────────────┤
 *  │                                              │ OrbitDesigner  │
 *  │ EarthViewport                          1fr   │   col-3        │
 *  │   col-9                                      │  (no scroll)   │
 *  ├──────────────────────────────────────────────┴────────────────┤
 *  │ SatelliteDetail (incl. sat dropdown in header)           120px│
 *  └───────────────────────────────────────────────────────────────┘
 *
 * Tracks: 74 / 1fr / 120. The event log and cost profile that used to sit
 * in a fourth row were dropped so the Omniverse viewport gets their height
 * (~154px) and the designer column is tall enough to hold the full design
 * flow — time window → propagator → pattern → parameters — without an
 * inner scrollbar.
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
        gridTemplateRows: '74px minmax(0, 1fr) 120px',
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
      {/* Right column — Orbit Designer (time window · propagator · pattern ·
          elements) with coverage and solar analytics as its other tabs. */}
      <div className="col-span-3 min-h-0 overflow-hidden">
        <OrbitDesignerPanel />
      </div>

      {/* overflow-visible + z-30: the satellite selector dropdown inside
          SatelliteDetail opens upward but still needs to escape this
          wrapper's clip box. */}
      <div className="col-span-12 min-h-0 overflow-visible relative z-30">
        <SatelliteDetail />
      </div>
    </div>
  )
}
