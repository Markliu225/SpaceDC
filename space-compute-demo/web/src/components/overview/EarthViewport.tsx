import { useEffect, useState } from 'react'
import {
  getStreamStatus, getStreamMessage, subscribeStreamStatus,
} from '../StreamMount'
import StreamConfig from '../../../stream.config.json'
import { Dot } from '../primitives'

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

      {/* Fallback / connecting placeholder — visible while stream is not ready.
          Phase C replaces this with the Three.js scene. */}
      {mode !== 'streaming' && (
        <PlaceholderEarth mode={mode} msg={msg} />
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

function PlaceholderEarth({ mode, msg }: { mode: 'connecting' | 'fallback'; msg: string }) {
  // A radial vignette + an SVG earth + atmosphere ring + 3 orbit arcs.
  return (
    <div className="absolute inset-0 grid place-items-center"
      style={{
        background:
          'radial-gradient(ellipse at center, #112347 0%, #060912 70%)',
      }}
    >
      {/* Earth + atmosphere */}
      <svg width="60%" height="60%" viewBox="-100 -100 200 200" preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="earth-fill" cx="35%" cy="30%" r="65%">
            <stop offset="0%"   stopColor="#2B5694" />
            <stop offset="60%"  stopColor="#10264E" />
            <stop offset="100%" stopColor="#040A18" />
          </radialGradient>
          <radialGradient id="atmo-fill" cx="50%" cy="50%" r="50%">
            <stop offset="80%"  stopColor="#3B9EFF" stopOpacity="0" />
            <stop offset="95%"  stopColor="#3B9EFF" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#3B9EFF" stopOpacity="0" />
          </radialGradient>
        </defs>
        {/* atmosphere halo */}
        <circle cx="0" cy="0" r="78" fill="url(#atmo-fill)" />
        {/* earth */}
        <circle cx="0" cy="0" r="62" fill="url(#earth-fill)" stroke="#3B9EFF" strokeOpacity="0.2" />
        {/* orbits */}
        {[0, 1, 2].map((i) => (
          <ellipse
            key={i}
            cx="0" cy="0"
            rx={78 + i * 4}
            ry={28 - i * 3}
            fill="none"
            stroke={['#22D3EE', '#E879F9', '#FBBF24'][i]}
            strokeOpacity="0.45"
            strokeWidth="0.8"
            transform={`rotate(${-20 + i * 18})`}
            className="animate-ribbon-breath"
            style={{ animationDelay: `${i * 800}ms` }}
          />
        ))}
      </svg>

      <div className="absolute bottom-6 left-1/2 -translate-x-1/2 text-center">
        {mode === 'connecting' ? (
          <div className="text-[11px] uppercase tracking-[0.14em] text-text-md">
            connecting to {StreamConfig.local.server}:{StreamConfig.local.signalingPort}…
          </div>
        ) : (
          <div className="text-[11px] uppercase tracking-[0.14em] text-warn">
            stream unavailable — local fallback ({msg || 'kit offline'})
          </div>
        )}
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
