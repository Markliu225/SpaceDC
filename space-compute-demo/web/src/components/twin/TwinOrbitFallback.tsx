import { Canvas, useFrame } from '@react-three/fiber'
import { Suspense, useMemo, useRef } from 'react'
import { Vector3 } from 'three'
import { Stars } from '../overview/earth/Stars'
import { useSatPosition } from '../../hooks/useFleetPositions'
import { useSmoothSimTime } from '../../hooks/useSmoothSimTime'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import {
  ConstellationRings, DayNightEarth, GmstWireframe, SatReticle, SunMarker,
} from './orbitScene'
import {
  EARTH_RADIUS_KM, SIDEREAL_DAY_S, SUN_DIR_ECI, eciToDisplay,
} from './orbitMath'

/**
 * TwinOrbitFallback — the Twin page's full-viewport LOCAL render when the
 * Omniverse stream is offline. Unlike the Overview page's decorative
 * FallbackEarth (mock fleet on stylised ribbons), this draws the REAL orbit:
 * the day/night Earth under the backend's fixed ECI sun, the active
 * constellation's true orbit ring(s), and the tracked satellite gliding
 * along its SGP4-propagated position on the smoothly-extrapolated sim clock
 * — so the "satellite moving around the Earth" story survives Kit being
 * down. A chase camera keeps the satellite in frame the whole orbit.
 */
export function TwinOrbitFallback() {
  const simTime   = useSmoothSimTime()
  const selected  = useTelemetryStore((s) => s.selectedSatIdx)
  const detail    = useTelemetryStore((s) => s.constellationDetail)
  const timeScale = detail?.time_scale ?? 60
  const sat       = useSatPosition(selected, simTime)

  const sunDir = useMemo(
    () => new Vector3(...eciToDisplay(SUN_DIR_ECI)).normalize(),
    [],
  )
  const gmst = (simTime * timeScale / SIDEREAL_DAY_S) * 2 * Math.PI

  const satPos = useMemo<[number, number, number] | null>(() => {
    if (!sat) return null
    const inv = 1 / EARTH_RADIUS_KM
    return eciToDisplay([sat.eci[0] * inv, sat.eci[1] * inv, sat.eci[2] * inv])
  }, [sat])

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      camera={{ position: [2.4, 1.3, 2.9], fov: 40 }}
      style={{
        position: 'absolute',
        inset: 0,
        background: 'radial-gradient(ellipse at center, #0A1224 0%, #03060E 70%)',
      }}
    >
      <ambientLight intensity={0.25} />
      <Suspense fallback={null}>
        <Stars />
      </Suspense>
      <DayNightEarth sunDir={sunDir} />
      <GmstWireframe gmst={gmst} />
      {detail && detail.ring_eci_km.length > 0 && sat && (
        <ConstellationRings detail={detail} selectedPlane={sat.planeIdx} />
      )}
      {satPos && <SatReticle pos={satPos} scale={1.6} />}
      <SunMarker dir={sunDir} />
      <ChaseCamera satPos={satPos} />
    </Canvas>
  )
}

/**
 * ChaseCamera — eases the camera around the Earth so the tracked satellite
 * never disappears behind the planet: the camera rides the satellite's
 * direction (offset ~28° in azimuth and lifted in elevation for depth),
 * always looking at the Earth's center. The result is the classic
 * "satellite sweeping around the globe" shot, continuously.
 */
function ChaseCamera({ satPos }: { satPos: [number, number, number] | null }) {
  const CAM_DIST = 3.1
  const AZ_OFFSET = 0.5           // rad — keep the sat off dead-center
  const POLAR_LIFT = 0.35         // rad — look slightly down on the orbit
  const desired = useRef(new Vector3(2.4, 1.3, 2.9))
  useFrame(({ camera }) => {
    if (satPos) {
      const [sx, sy, sz] = satPos
      const az = Math.atan2(sx, sz) + AZ_OFFSET
      const polar = Math.max(0.35, Math.min(2.2,
        Math.acos(Math.max(-1, Math.min(1, sy / (Math.hypot(sx, sy, sz) || 1)))) - POLAR_LIFT))
      desired.current.set(
        CAM_DIST * Math.sin(polar) * Math.sin(az),
        CAM_DIST * Math.cos(polar),
        CAM_DIST * Math.sin(polar) * Math.cos(az),
      )
    }
    camera.position.lerp(desired.current, 0.03)
    camera.lookAt(0, 0, 0)
  })
  return null
}
