import { useEffect } from 'react'
import { useDemoStore } from '../store/demoStore'
import { useBackendBridge } from '../hooks/useBackendBridge'
import { useMockTelemetryFeed } from '../hooks/useMockTelemetryFeed'
import { EarthViewport } from '../components/overview/EarthViewport'
import { SatelliteSelector } from '../components/overview/SatelliteSelector'
import { ComparePanel } from '../components/twin/ComparePanel'
import { Configurator } from '../components/twin/Configurator'
import { DesignGallery } from '../components/twin/DesignGallery'
import { MiniOrbitHud } from '../components/twin/MiniOrbitHud'
import { TwinModulePopup } from '../components/twin/TwinModulePopup'
import { TimeSeriesStrip } from '../components/twin/TimeSeriesStrip'
import { SatelliteBuilder } from '../components/twin/builder/SatelliteBuilder'
import { BuilderChip } from '../components/twin/builder/BuilderChip'
import { useBuilderStore } from '../store/useBuilderStore'

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
 *  │ TimeSeriesStrip · 5 charts · 120 s            col-12 · 224 px      │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 * Tracks: 56 / 1fr / 224. The viewport keeps a satellite-preset camera;
 * the Configurator + strip stay reactive via useTwinTelemetry.
 */
export function SatelliteTwinPage() {
  const changeCamera = useDemoStore((s) => s.changeCamera)
  const connected    = useDemoStore((s) => s.connected)
  const builderOpen  = useBuilderStore((s) => s.open)
  useEffect(() => {
    if (connected) changeCamera('satellite')
  }, [connected, changeCamera])

  // Drive the shared global tick + backend mirror so other components
  // (time-series strip, configurator) see fresh values.
  useMockTelemetryFeed()
  useBackendBridge()

  // The build flow owns the whole page while it runs: selecting a platform,
  // fitting slots and reading the design check all want the space, and the
  // viewport would be showing the PREVIOUS satellite anyway (nothing is
  // applied until Run). Everything below is untouched once it closes.
  if (builderOpen) {
    return (
      <div
        className="w-full bg-bg-app font-sans text-text-md overflow-hidden"
        style={{ height: 'calc(100vh - 44px - 24px - 4px)' }}
      >
        <SatelliteBuilder />
      </div>
    )
  }

  return (
    <div
      className="grid w-full bg-bg-app font-sans text-text-md gap-2.5 overflow-hidden"
      style={{
        height: 'calc(100vh - 44px - 24px - 4px)',
        gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
        gridTemplateRows: '56px minmax(0, 1fr) 224px',
      }}
    >
      {/* Row 1 — Header strip. */}
      <div className="col-span-12 flex items-center justify-between rounded border border-border-weak bg-card px-3 min-h-0">
        <div className="flex items-center gap-3">
          <span className="text-[11px] uppercase tracking-[0.10em] text-text-md">
            Satellite Twin
          </span>
          <SatelliteSelector />
          <BuilderChip />
          <DesignGallery />
          <ComparePanel />
        </div>
        <div className="text-[10px] uppercase tracking-[0.10em] text-text-lo">
          {connected ? 'Live · Streaming' : 'Offline'}
        </div>
      </div>

      {/* Row 2 — Viewport + Configurator. The viewport cell is `relative` so
          the HUD overlays (MiniOrbitHud bottom-left, TwinModulePopup top-right
          when a module is clicked) can anchor inside it. */}
      <div className="col-span-9 min-h-0 overflow-hidden relative">
        <EarthViewport fallback="twin" />
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
    </div>
  )
}
