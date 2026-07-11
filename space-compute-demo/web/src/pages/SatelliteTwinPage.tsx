import { useEffect, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useBackendBridge } from '../hooks/useBackendBridge'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { EarthViewport } from '../components/overview/EarthViewport'
import { SatelliteSelector } from '../components/overview/SatelliteSelector'
import { Configurator } from '../components/twin/Configurator'
import { DesignGallery } from '../components/twin/DesignGallery'
import { MiniOrbitHud } from '../components/twin/MiniOrbitHud'
import { TwinModulePopup } from '../components/twin/TwinModulePopup'
import { SubsystemHealthRow } from '../components/twin/SubsystemHealthRow'
import { TimeSeriesStrip } from '../components/twin/TimeSeriesStrip'
import { ViewModeTabs, type TwinViewMode } from '../components/twin/ViewModeTabs'

/**
 * SatelliteTwinPage — single-satellite deep dive. Targets 1440×900.
 *
 * AppShell adds 44 (header) + 24 (padding) → usable 832 px.
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │ Header: sat picker · view-mode tabs · LIVE                  56px   │
 *  ├──────────────────────────────────────────────┬─────────────────────┤
 *  │ Omniverse viewport (col-9)            1fr      │ Configurator col-3│
 *  │                                                │   3 sections + Δ  │
 *  ├────────────────────────────────────────────────┴───────────────────┤
 *  │ TimeSeriesStrip · 5 sparklines · 120 s        col-12 · 150 px      │
 *  ├────────────────────────────────────────────────────────────────────┤
 *  │ SubsystemHealthRow · 4 cards                  col-12 · 88 px       │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 * Tracks: 56 / 1fr / 150 / 88. The viewport keeps a satellite-preset
 * camera (Kit will respond once Phase 3 lands); the Configurator + bars
 * stay reactive in Phase 1 via the local useTwinTelemetry synth.
 */
export function SatelliteTwinPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera)
  const connected    = useDemoStore((s) => s.connected)
  useEffect(() => {
    if (connected) changeCamera('satellite')
  }, [connected, changeCamera])

  // Drive the shared global tick + backend mirror so other components
  // (Subsystem cards, time-series strip) see fresh values.
  useMockTelemetryFeed()
  useBackendBridge()

  const [viewMode, setViewMode] = useState<TwinViewMode>('structure')

  return (
    <div
      className="grid w-full bg-bg-app font-sans text-text-md gap-2.5 overflow-hidden"
      style={{
        height: 'calc(100vh - 44px - 24px - 4px)',
        gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
        gridTemplateRows: '56px minmax(0, 1fr) 150px 88px',
      }}
    >
      {/* Row 1 — Header strip. */}
      <div className="col-span-12 flex items-center justify-between rounded border border-border-weak bg-card px-3 min-h-0">
        <div className="flex items-center gap-3">
          <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
            Satellite Twin
          </span>
          <SatelliteSelector />
          <DesignGallery />
        </div>
        <ViewModeTabs value={viewMode} onChange={setViewMode} />
        <div className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          {connected ? 'Live · Streaming' : 'Offline'}
        </div>
      </div>

      {/* Row 2 — Viewport + Configurator. The viewport cell is `relative` so
          the HUD overlays (MiniOrbitHud bottom-left, TwinModulePopup top-right
          when a module is clicked) can anchor inside it. */}
      <div className="col-span-9 min-h-0 overflow-hidden relative">
        <EarthViewport />
        <MiniOrbitHud />
        <TwinModulePopup />
      </div>
      <div className="col-span-3 min-h-0 overflow-visible relative z-20">
        <Configurator />
      </div>

      {/* Row 3 — Time series strip (full width). */}
      <div className="col-span-12 min-h-0 overflow-hidden">
        <TimeSeriesStrip />
      </div>

      {/* Row 4 — Subsystem health (full width, 4 cards). */}
      <div className="col-span-12 min-h-0 overflow-hidden">
        <SubsystemHealthRow />
      </div>
    </div>
  )
}
