import { Suspense, lazy, useEffect, useState } from 'react'
import {
  getStreamStatus, getStreamMessage, subscribeStreamStatus,
} from '../StreamMount'
import StreamConfig from '../../../stream.config.json'
import { Dot } from '../primitives'

// Lazy-load the Three.js scene so it doesn't bloat the initial JS bundle.
const FallbackEarth = lazy(() =>
  import('./earth/FallbackEarth').then((m) => ({ default: m.FallbackEarth })),
)

/**
 * EarthViewport — the centerpiece slot. In Phase B we are still
 * positioning the Omniverse AppStreamer over `#scene-embed-slot` (see
 * StreamMount). This component contributes:
 *
 *   - The 3D slot div with id="scene-embed-slot" so StreamMount picks it up.
 *   - The atmospheric vignette background visible while the stream is
 *     connecting or failed.
 *   - Top-left status chip: OMNIVERSE ● STREAMING (ok) /
 *                            OMNIVERSE ● CONNECTING (info) /
 *                            LOCAL ● FALLBACK (warn).
 *   - Bottom-right compass/axis gizmo (64x64 svg).
 *   - Selected satellite cyan ring + crosshair marker (overlay).
 *
 * Phase C swaps the placeholder fallback for a real Three.js scene
 * (PBR earth + atmosphere + 24 ribbons + bloom).
 */
type ViewportMode = 'streaming' | 'connecting' | 'fallback'

export function EarthViewport() {
  const [, tick] = useState(0)
  useEffect(() => subscribeStreamStatus(() => tick((t) => t + 1)), [])
  const status = getStreamStatus()
  const msg    = getStreamMessage()

  const mode: ViewportMode =
    status === 'ready'      ? 'streaming' :
    status === 'connecting' ? 'connecting' :
                              'fallback'

  return (
    <div className="relative h-full w-full overflow-hidden rounded-[10px] border border-border-weak bg-bg-inset shadow-card">
      {/* The slot StreamMount positions the WebRTC <video> over. */}
      <div
        id="scene-embed-slot"
        className="absolute inset-0"
      />

      {/* Fallback Three.js scene — mounts only when the stream isn't ready. */}
      {mode !== 'streaming' && (
        <div className="absolute inset-0">
          <Suspense fallback={<PlaceholderEarth mode={mode} msg={msg} />}>
            <FallbackEarth />
          </Suspense>
          <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 text-center">
            {mode === 'connecting' ? (
              <div className="rounded bg-bg-app/60 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-text-md backdrop-blur">
                connecting to {StreamConfig.local.server}:{StreamConfig.local.signalingPort}…
              </div>
            ) : (
              <div className="rounded bg-bg-app/60 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-warn backdrop-blur">
                stream unavailable — local fallback{msg ? ` (${msg})` : ''}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Top-left status chip */}
      <div className="absolute left-3 top-3 z-10 flex items-center gap-2 rounded-full border border-border-weak bg-bg-app/70 px-2.5 py-1 text-[10px] uppercase tracking-[0.14em] backdrop-blur">
        <Dot
          color={mode === 'streaming' ? '#22C55E' : mode === 'connecting' ? '#3B9EFF' : '#F59E0B'}
          size={7}
          glow={6}
          pulse={mode !== 'fallback'}
        />
        <span className="text-text-md">
          {mode === 'streaming'
            ? <>Omniverse <span className="text-ok">streaming</span></>
            : mode === 'connecting'
            ? <>Omniverse <span className="text-accent">connecting…</span></>
            : <>Local <span className="text-warn">fallback</span></>}
        </span>
      </div>

      {/* Bottom-right compass/axis gizmo */}
      <CompassGizmo />
    </div>
  )
}

// Lightweight Suspense fallback shown for the brief moment before the
// Three.js scene's chunk finishes downloading.
function PlaceholderEarth({ mode, msg }: { mode: 'connecting' | 'fallback'; msg: string }) {
  void mode; void msg
  return (
    <div className="absolute inset-0 grid place-items-center"
      style={{
        background: 'radial-gradient(ellipse at center, #0A1224 0%, #03060E 70%)',
      }}
    >
      <div className="text-[11px] uppercase tracking-[0.18em] text-text-lo animate-twinkle">
        loading scene…
      </div>
    </div>
  )
}

function CompassGizmo() {
  return (
    <svg
      width="64"
      height="64"
      viewBox="-32 -32 64 64"
      className="absolute bottom-3 right-3 z-10 opacity-60"
      aria-hidden="true"
    >
      <circle cx="0" cy="0" r="22" fill="none" stroke="#6B7691" strokeOpacity="0.5" strokeWidth="0.5" />
      <circle cx="0" cy="0" r="2" fill="#E8EEFB" />
      <line x1="0" y1="-22" x2="0" y2="-26" stroke="#E8EEFB" strokeWidth="1.4" />
      <line x1="0" y1="22"  x2="0" y2="26"  stroke="#6B7691" strokeWidth="1" />
      <line x1="-22" y1="0" x2="-26" y2="0" stroke="#6B7691" strokeWidth="1" />
      <line x1="22"  y1="0" x2="26"  y2="0" stroke="#6B7691" strokeWidth="1" />
      <text x="0" y="-12" textAnchor="middle" fontSize="6" fill="#E8EEFB" fontFamily="JetBrains Mono">N</text>
    </svg>
  )
}
