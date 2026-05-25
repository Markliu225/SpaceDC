import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useTelemetryStore } from '../store/useTelemetryStore'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { Dot } from '../components/primitives'
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
 * OverviewPage — mission-control layout. Grid is desktop-only (min 1280,
 * ideal 1440+). Per brief, structure:
 *
 *  ┌────────────────────────────────────────────────────────────────┐
 *  │ NetworkOverview (4 KPI tiles, full-width)                       │
 *  ├──────────────────────────────────┬─────────────────────────────┤
 *  │ EarthViewport (centerpiece)       │ SatelliteStatus              │
 *  │                                   │ LinkAndTraffic               │
 *  │                                   │ SystemHealth                 │
 *  ├──────────────────────────────────┴─────────────────────────────┤
 *  │ SelectedSatellite (full width)                                  │
 *  ├────────────────────────┬───────────────────────────────────────┤
 *  │ CoverageMap            │ EventLog        │  UpcomingEvents      │
 *  └────────────────────────┴─────────────────┴───────────────────────┘
 *
 * The legacy DemoStore (WebSocket to backend) is still wired so the
 * stream camera preset gets nudged to "overview", but telemetry numbers
 * here come from the new mock feed per brief.
 */
export function OverviewPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera)
  const connected    = useDemoStore((s) => s.connected)

  useEffect(() => {
    if (connected) changeCamera('overview')
  }, [connected, changeCamera])

  // Drive 1Hz mock feed (AppShell already bridges Play/Pause to running).
  useMockTelemetryFeed()

  return (
    <OverviewLayout>
      <HeaderStrip />

      {/* Row 1: KPI strip */}
      <div className="col-span-12">
        <NetworkOverview />
      </div>

      {/* Row 2: viewport + right rail */}
      <div className="col-span-8 min-h-[420px]">
        <EarthViewport />
      </div>
      <div className="col-span-4 flex flex-col gap-3">
        <SatelliteStatus />
        <LinkAndTraffic />
        <SystemHealth />
      </div>

      {/* Row 3: selected satellite (full width) */}
      <div className="col-span-12">
        <SelectedSatellite />
      </div>

      {/* Row 4: coverage / event log / upcoming */}
      <div className="col-span-5">
        <CoverageMap />
      </div>
      <div className="col-span-4">
        <EventLog />
      </div>
      <div className="col-span-3">
        <UpcomingEvents />
      </div>
    </OverviewLayout>
  )
}

function OverviewLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full w-full bg-bg-app px-4 py-3 font-sans text-text-md">
      <div className="grid grid-cols-12 gap-3">
        {children}
      </div>
    </div>
  )
}

function HeaderStrip() {
  const running = useTelemetryStore((s) => s.running)
  return (
    <div className="col-span-12 flex items-center justify-between rounded-[10px] border border-border-weak bg-card px-4 py-2.5 shadow-card">
      <div className="flex items-center gap-4">
        <span className="text-[12px] uppercase tracking-[0.18em] text-accent">
          Mission Overview
        </span>
        <span className="text-[11px] uppercase tracking-[0.14em] text-text-lo">
          1 MW · LEO/SSO · 24-node constellation
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Dot color={running ? '#22C55E' : '#6B7691'} size={8} glow={6} pulse={running} />
        <span className="text-[11px] uppercase tracking-[0.14em] text-text-md">
          {running ? 'Live' : 'Paused'}
        </span>
      </div>
    </div>
  )
}
