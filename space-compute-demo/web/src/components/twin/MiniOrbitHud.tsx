import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo } from 'react'
import {
  AdditiveBlending, BackSide, CatmullRomCurve3, ShaderMaterial,
  TubeGeometry, Vector3,
} from 'three'
import { earthVert, earthFrag, atmoVert, atmoFrag }
  from '../overview/earth/shaders'
import { useFleetPositions } from '../../hooks/useFleetPositions'
import { useTelemetryStore } from '../../store/useTelemetryStore'

/**
 * MiniOrbitHud — 208×208 HUD overlay on the Twin viewport. Shows a small
 * procedural Earth + the selected satellite's orbit ring + a glowing dot at
 * its current ECI position. The Earth terminator is driven by the SAME
 * `SUN_DIR_ECI` constant the backend uses for sun_factor (see
 * services/constellations.py and hooks/useFleetPositions.ts), so the
 * sunlit/eclipse state on the widget matches the satellite stage lighting
 * in the main viewport.
 *
 * Display frame: Y-up, geometry static — the Earth doesn't physically
 * rotate, the sun direction is fixed in ECI. The sat dot moves along the
 * orbit and visibly crosses the day/night line.
 */

const EARTH_RADIUS_KM = 6378.137
const SUN_DIR_ECI: [number, number, number] = [0.648, -0.648, 0.398]

/** ECI (z = north pole) → Three.js display coords (Y-up). */
function eciToDisplay([x, y, z]: [number, number, number]): [number, number, number] {
  return [x, z, -y]
}

function MiniEarth({ sunDir }: { sunDir: Vector3 }) {
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: earthVert,
    fragmentShader: earthFrag,
    uniforms: {
      uSunDir: { value: sunDir.clone() },
      uTime:   { value: 0 },
    },
  }), [sunDir])
  useFrame((_, dt) => {
    material.uniforms.uTime.value += dt
    material.uniforms.uSunDir.value.copy(sunDir)
  })
  return (
    <mesh>
      <sphereGeometry args={[1, 64, 64]} />
      <primitive object={material} attach="material" />
    </mesh>
  )
}

function MiniAtmosphere() {
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: atmoVert,
    fragmentShader: atmoFrag,
    uniforms: {
      uColor:     { value: new Vector3(0.23, 0.62, 1.0) },
      uIntensity: { value: 1.1 },
    },
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    side: BackSide,
  }), [])
  return (
    <mesh>
      <sphereGeometry args={[1.06, 32, 32]} />
      <primitive object={material} attach="material" />
    </mesh>
  )
}

function OrbitRing({ points }: { points: [number, number, number][] }) {
  // TubeGeometry instead of a Line because WebGL clamps lineWidth to 1px —
  // the orbit would otherwise be invisible against the Earth at 208 px.
  const geom = useMemo(() => {
    const pts = points.map(([x, y, z]) => new Vector3(x, y, z))
    const curve = new CatmullRomCurve3(pts, true, 'catmullrom', 0.5)
    return new TubeGeometry(curve, 160, 0.018, 6, true)
  }, [points])
  return (
    <mesh>
      <primitive object={geom} attach="geometry" />
      <meshBasicMaterial color="#3B9EFF" transparent opacity={0.85} />
    </mesh>
  )
}

function SatDot({ pos }: { pos: [number, number, number] }) {
  return (
    <group position={pos}>
      <mesh>
        <sphereGeometry args={[0.055, 16, 16]} />
        <meshBasicMaterial color="#22D3EE" />
      </mesh>
      {/* Additive halo so the dot reads against the lit Earth + tube. */}
      <mesh>
        <sphereGeometry args={[0.11, 12, 12]} />
        <meshBasicMaterial
          color="#22D3EE"
          transparent
          opacity={0.35}
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

export function MiniOrbitHud() {
  const fleet    = useFleetPositions()
  const selected = useTelemetryStore((s) => s.selectedSatIdx)
  const detail   = useTelemetryStore((s) => s.constellationDetail)
  const sat      = fleet[selected]

  const sunDir = useMemo(
    () => new Vector3(...eciToDisplay(SUN_DIR_ECI)).normalize(),
    [],
  )

  // Orbit ring — ring_eci_km is the base plane; rotate by the selected
  // sat's planeAngle, scale to Earth-radius=1, convert to display coords.
  const orbitPoints = useMemo<[number, number, number][]>(() => {
    if (!detail || !sat) return []
    const { ring_eci_km, planes } = detail
    const ang = (sat.planeIdx * 2 * Math.PI) / planes
    const ca = Math.cos(ang), sa = Math.sin(ang)
    const inv = 1 / EARTH_RADIUS_KM
    return ring_eci_km.map(([x, y, z]) => {
      const rx = x * ca - y * sa
      const ry = x * sa + y * ca
      return eciToDisplay([rx * inv, ry * inv, z * inv])
    })
  }, [detail, sat?.planeIdx])

  const satPos = useMemo<[number, number, number] | null>(() => {
    if (!sat) return null
    const inv = 1 / EARTH_RADIUS_KM
    return eciToDisplay([sat.eci[0] * inv, sat.eci[1] * inv, sat.eci[2] * inv])
  }, [sat?.eci])

  return (
    <div className="absolute right-3 top-3 z-10 pointer-events-none">
      <div className="pointer-events-auto h-[208px] w-[208px] rounded-[10px] border border-border-weak bg-bg-app/70 backdrop-blur shadow-card overflow-hidden flex flex-col">
        <div className="px-2.5 pt-1.5 pb-1 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.14em] text-text-md">
            Orbit Track
          </span>
          <span className={`text-[10px] uppercase tracking-[0.12em] ${sat?.sunlit ? 'text-ok' : 'text-warn'}`}>
            {sat ? (sat.sunlit ? 'Sunlit' : 'Eclipse') : '—'}
          </span>
        </div>
        <div className="flex-1 min-h-0">
          <Canvas
            camera={{ position: [0, 0.6, 3.4], fov: 32 }}
            gl={{ antialias: true, alpha: true }}
            style={{ background: 'radial-gradient(ellipse at center, #0A1224 0%, #03060E 70%)' }}
          >
            <ambientLight intensity={0.25} />
            <MiniEarth sunDir={sunDir} />
            <MiniAtmosphere />
            {orbitPoints.length > 0 && <OrbitRing points={orbitPoints} />}
            {satPos && <SatDot pos={satPos} />}
          </Canvas>
        </div>
        <div className="px-2.5 pb-1.5 pt-0.5 flex items-center justify-between text-[9px] text-text-lo font-mono">
          <span>{sat ? `lat ${sat.lat >= 0 ? '+' : ''}${sat.lat.toFixed(1)}°` : '—'}</span>
          <span>{sat ? `lon ${sat.lon >= 0 ? '+' : ''}${sat.lon.toFixed(1)}°` : '—'}</span>
          <span>{sat ? `${Math.round(sat.altitudeKm)} km` : '—'}</span>
        </div>
      </div>
    </div>
  )
}
