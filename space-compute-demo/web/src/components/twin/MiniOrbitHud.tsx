import { Canvas } from '@react-three/fiber'
import { useMemo } from 'react'
import { Vector3 } from 'three'
import { useFleetPositions } from '../../hooks/useFleetPositions'
import { useSmoothSimTime } from '../../hooks/useSmoothSimTime'
import { useDemoStore } from '../../store/demoStore'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import {
  ConstellationRings, DayNightEarth, GmstWireframe, SatReticle, SunMarker,
} from './orbitScene'
import {
  EARTH_RADIUS_KM, HUD_CYAN_HOT, HUD_WARN, SIDEREAL_DAY_S, SUN_DIR_ECI,
  eciToDisplay,
} from './orbitMath'

/**
 * MiniOrbitHud — sci-fi holographic HUD at the bottom-left of the Satellite
 * Twin viewport. Shows the active constellation (every plane's orbit ring),
 * highlights the selected sat's plane, places the sat as a pulsing reticle,
 * a sun marker at SUN_DIR_ECI, and a solid day/night Earth sphere whose
 * terminator is computed from the SAME sun direction the backend uses for
 * `sun_factor`. The reticle + wireframe animate on the smoothly-extrapolated
 * sim clock (useSmoothSimTime) so the orbital motion glides at frame rate
 * instead of jumping once per second.
 */

function Brackets() {
  const base = 'absolute w-2.5 h-2.5 border-[#3B9EFF]'
  return (
    <>
      <div className={`${base} left-0 top-0 border-l border-t`} />
      <div className={`${base} right-0 top-0 border-r border-t`} />
      <div className={`${base} left-0 bottom-0 border-l border-b`} />
      <div className={`${base} right-0 bottom-0 border-r border-b`} />
    </>
  )
}

export function MiniOrbitHud() {
  // Frame-rate extrapolated sim clock — the reticle glides along its orbit
  // instead of jumping once per 1 Hz store tick.
  const simTime   = useSmoothSimTime()
  const fleet     = useFleetPositions(simTime)
  const selected  = useTelemetryStore((s) => s.selectedSatIdx)
  const detail    = useTelemetryStore((s) => s.constellationDetail)
  const timeScale = detail?.time_scale ?? 60
  // The physics engine tracks fleet[0]; when it is the selected sat and the
  // backend is live, the badge + LAT/LON/ALT read the engine's authoritative
  // values so the HUD can never contradict the telemetry panels (the local
  // propagation only positions the 3D dot).
  const backendSat = useDemoStore((s) => s.lastState?.satellite)
  const local = fleet[selected]
  const sat = (selected === 0 && backendSat && local)
    ? { ...local,
        sunlit: backendSat.sunlit,
        lat: backendSat.lat,
        lon: backendSat.lon,
        altitudeKm: backendSat.altitude_km }
    : local

  const sunDir = useMemo(
    () => new Vector3(...eciToDisplay(SUN_DIR_ECI)).normalize(),
    [],
  )
  const gmst = useMemo(
    () => (simTime * timeScale / SIDEREAL_DAY_S) * 2 * Math.PI,
    [simTime, timeScale],
  )

  const satPos = useMemo<[number, number, number] | null>(() => {
    if (!sat) return null
    const inv = 1 / EARTH_RADIUS_KM
    return eciToDisplay([sat.eci[0] * inv, sat.eci[1] * inv, sat.eci[2] * inv])
  }, [sat])

  const constellationId = detail?.id?.toUpperCase().replace(/_/g, '-') ?? 'STDBY'

  return (
    <div className="absolute left-3 bottom-3 z-10 pointer-events-none">
      <div className="pointer-events-auto relative h-[200px] w-[180px] bg-[#040912]/85 backdrop-blur-sm">
        <div
          className="absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              'linear-gradient(rgba(59,158,255,0.06) 1px, transparent 1px),'
              + 'linear-gradient(90deg, rgba(59,158,255,0.06) 1px, transparent 1px)',
            backgroundSize: '12px 12px',
          }}
        />
        <Brackets />

        <div className="absolute left-1.5 right-1.5 top-1.5 flex items-center justify-between">
          <span className="text-[8px] uppercase tracking-[0.18em] text-[#3B9EFF] font-mono">
            ▸ {constellationId}
          </span>
          <span
            className="text-[8px] uppercase tracking-[0.16em] font-mono"
            style={{ color: sat?.sunlit ? HUD_CYAN_HOT : HUD_WARN }}
          >
            {sat ? (sat.sunlit ? '◉ SUNLIT' : '○ ECLIPSE') : '— STDBY'}
          </span>
        </div>

        <div className="absolute left-1.5 right-1.5 top-[18px] flex items-center justify-between">
          <span className="text-[7.5px] tracking-[0.16em] text-[#3B9EFF]/80 font-mono">
            SAT-{String(selected).padStart(3, '0')}
          </span>
          <span className="text-[7.5px] tracking-[0.16em] text-[#3B9EFF]/80 font-mono">
            {detail ? `${detail.planes}P × ${detail.sats_per_plane}S` : ''}
          </span>
        </div>

        <div className="absolute inset-x-1 top-[32px] bottom-[44px]">
          <Canvas
            camera={{ position: [2.7, 1.6, 3.2], fov: 32 }}
            gl={{ antialias: true, alpha: true }}
          >
            <ambientLight intensity={0.3} />
            <DayNightEarth sunDir={sunDir} />
            <GmstWireframe gmst={gmst} />
            {detail && detail.ring_eci_km.length > 0 && sat && (
              <ConstellationRings detail={detail} selectedPlane={sat.planeIdx} />
            )}
            {satPos && <SatReticle pos={satPos} />}
            <SunMarker dir={sunDir} />
          </Canvas>
        </div>

        <div className="absolute left-1.5 right-1.5 bottom-1.5 flex flex-col gap-[1px] text-[8px] font-mono leading-[1.25]">
          <div className="flex justify-between text-[#3B9EFF]/85">
            <span>LAT</span>
            <span className="text-[#E0F0FF]">
              {sat ? `${sat.lat >= 0 ? '+' : ''}${sat.lat.toFixed(1)}°` : '— —'}
            </span>
          </div>
          <div className="flex justify-between text-[#3B9EFF]/85">
            <span>LON</span>
            <span className="text-[#E0F0FF]">
              {sat ? `${sat.lon >= 0 ? '+' : ''}${sat.lon.toFixed(1)}°` : '— —'}
            </span>
          </div>
          <div className="flex justify-between text-[#3B9EFF]/85">
            <span>ALT</span>
            <span className="text-[#E0F0FF]">
              {sat ? `${Math.round(sat.altitudeKm)} KM` : '— —'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
