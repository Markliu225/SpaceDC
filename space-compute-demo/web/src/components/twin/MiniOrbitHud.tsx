import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import {
  AdditiveBlending, BackSide, BufferAttribute, BufferGeometry,
  CatmullRomCurve3, DoubleSide, Group, Mesh, MeshBasicMaterial,
  ShaderMaterial, TubeGeometry, Vector3,
} from 'three'
import { atmoVert, atmoFrag } from '../overview/earth/shaders'
import { useFleetPositions } from '../../hooks/useFleetPositions'
import { useTelemetryStore } from '../../store/useTelemetryStore'
import type { ConstellationDetail } from '../../types/messages'

/**
 * MiniOrbitHud — sci-fi holographic constellation HUD at the bottom-left of
 * the Satellite Twin viewport. Shows:
 *   - the whole active constellation (every plane's orbit ring, faint cyan)
 *   - the SELECTED satellite's plane highlighted (thicker bright tube)
 *   - the selected sat as a pulsing reticle at its live ECI position
 *   - a sun marker placed at SUN_DIR_ECI — the SAME constant the backend uses
 *     for sun_factor, so the SUNLIT/ECLIPSE badge flips in step with the
 *     satellite stage's lighting transitions
 *   - a wireframe lat/lon Earth rotating at the true GMST rate (sidereal day
 *     scaled by the constellation's time_scale) so the Earth rotation, the
 *     sat's orbital motion, and the sunlit/eclipse state all share one clock
 */

const EARTH_RADIUS_KM = 6378.137
const SIDEREAL_DAY_S = 86164.0905
const SUN_DIR_ECI: [number, number, number] = [0.648, -0.648, 0.398]
const HUD_CYAN     = '#3B9EFF'
const HUD_CYAN_HOT = '#22D3EE'
const HUD_WARN     = '#F59E0B'

/** ECI (z = north pole) → Three.js display coords (Y-up). */
function eciToDisplay([x, y, z]: [number, number, number]): [number, number, number] {
  return [x, z, -y]
}

/** Clean lat/lon wireframe — N parallels + M meridians. */
function makeLatLonGrid(radius: number, parallels: number, meridians: number): BufferGeometry {
  const pts: number[] = []
  const SEGS = 64
  for (let i = 1; i < parallels; i++) {
    const lat = -Math.PI / 2 + (i / parallels) * Math.PI
    const r = radius * Math.cos(lat)
    const y = radius * Math.sin(lat)
    for (let j = 0; j < SEGS; j++) {
      const a0 = (j / SEGS) * 2 * Math.PI
      const a1 = ((j + 1) / SEGS) * 2 * Math.PI
      pts.push(r * Math.cos(a0), y, r * Math.sin(a0))
      pts.push(r * Math.cos(a1), y, r * Math.sin(a1))
    }
  }
  for (let i = 0; i < meridians; i++) {
    const lon = (i / meridians) * 2 * Math.PI
    for (let j = 0; j < SEGS; j++) {
      const t0 = -Math.PI / 2 + (j / SEGS) * Math.PI
      const t1 = -Math.PI / 2 + ((j + 1) / SEGS) * Math.PI
      const r0 = radius * Math.cos(t0), y0 = radius * Math.sin(t0)
      const r1 = radius * Math.cos(t1), y1 = radius * Math.sin(t1)
      pts.push(r0 * Math.cos(lon), y0, r0 * Math.sin(lon))
      pts.push(r1 * Math.cos(lon), y1, r1 * Math.sin(lon))
    }
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new BufferAttribute(new Float32Array(pts), 3))
  return g
}

function makeEquatorRing(radius: number): BufferGeometry {
  const pts: number[] = []
  const SEGS = 96
  for (let j = 0; j < SEGS; j++) {
    const a0 = (j / SEGS) * 2 * Math.PI
    const a1 = ((j + 1) / SEGS) * 2 * Math.PI
    pts.push(radius * Math.cos(a0), 0, radius * Math.sin(a0))
    pts.push(radius * Math.cos(a1), 0, radius * Math.sin(a1))
  }
  const g = new BufferGeometry()
  g.setAttribute('position', new BufferAttribute(new Float32Array(pts), 3))
  return g
}

function GmstEarth({ gmst }: { gmst: number }) {
  const ref = useRef<Group>(null!)
  const grid = useMemo(() => makeLatLonGrid(1.0, 7, 8), [])
  const equator = useMemo(() => makeEquatorRing(1.0), [])
  useFrame(() => { if (ref.current) ref.current.rotation.y = gmst })
  return (
    <group ref={ref}>
      <lineSegments>
        <primitive object={grid} attach="geometry" />
        <lineBasicMaterial color="#1E5A99" transparent opacity={0.55} />
      </lineSegments>
      <lineSegments>
        <primitive object={equator} attach="geometry" />
        <lineBasicMaterial color={HUD_CYAN} transparent opacity={0.7} />
      </lineSegments>
    </group>
  )
}

function MiniAtmosphere() {
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: atmoVert,
    fragmentShader: atmoFrag,
    uniforms: {
      uColor:     { value: new Vector3(0.23, 0.62, 1.0) },
      uIntensity: { value: 0.8 },
    },
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    side: BackSide,
  }), [])
  return (
    <mesh>
      <sphereGeometry args={[1.05, 32, 32]} />
      <primitive object={material} attach="material" />
    </mesh>
  )
}

function ConstellationRings({
  detail, selectedPlane,
}: { detail: ConstellationDetail; selectedPlane: number }) {
  const rings = useMemo(() => {
    const inv = 1 / EARTH_RADIUS_KM
    return Array.from({ length: detail.planes }, (_, k) => {
      const ang = (k * 2 * Math.PI) / detail.planes
      const ca = Math.cos(ang), sa = Math.sin(ang)
      const pts = detail.ring_eci_km.map(([x, y, z]) => {
        const rx = x * ca - y * sa
        const ry = x * sa + y * ca
        const d = eciToDisplay([rx * inv, ry * inv, z * inv])
        return new Vector3(d[0], d[1], d[2])
      })
      const curve = new CatmullRomCurve3(pts, true, 'catmullrom', 0.5)
      const isSel = k === selectedPlane
      const geom = new TubeGeometry(curve, 96, isSel ? 0.020 : 0.0085, isSel ? 6 : 4, true)
      return { k, geom, isSel }
    })
  }, [detail, selectedPlane])
  return (
    <>
      {rings.map(({ k, geom, isSel }) => (
        <mesh key={k}>
          <primitive object={geom} attach="geometry" />
          <meshBasicMaterial
            color={isSel ? HUD_CYAN_HOT : HUD_CYAN}
            transparent
            opacity={isSel ? 0.95 : 0.62}
            depthWrite={false}
            blending={AdditiveBlending}
          />
        </mesh>
      ))}
    </>
  )
}

function SatReticle({ pos }: { pos: [number, number, number] }) {
  const haloRef = useRef<Mesh>(null!)
  useFrame(({ clock }) => {
    if (!haloRef.current) return
    const t = (clock.getElapsedTime() % 1.8) / 1.8   // 0..1 over 1.8 s
    const s = 1 + t * 3.5
    haloRef.current.scale.set(s, s, s)
    ;(haloRef.current.material as MeshBasicMaterial).opacity = (1 - t) * 0.75
  })
  return (
    <group position={pos}>
      <mesh>
        <sphereGeometry args={[0.04, 12, 12]} />
        <meshBasicMaterial color={HUD_CYAN_HOT} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.085, 12, 12]} />
        <meshBasicMaterial
          color={HUD_CYAN_HOT} transparent opacity={0.4}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
      <mesh ref={haloRef}>
        <ringGeometry args={[0.05, 0.07, 32]} />
        <meshBasicMaterial
          color={HUD_CYAN_HOT} transparent opacity={0.7}
          side={DoubleSide} depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

function SunMarker({ dir }: { dir: Vector3 }) {
  const pos = useMemo<[number, number, number]>(
    () => [dir.x * 2.6, dir.y * 2.6, dir.z * 2.6],
    [dir],
  )
  return (
    <group position={pos}>
      <mesh>
        <sphereGeometry args={[0.07, 12, 12]} />
        <meshBasicMaterial color="#FFE9B0" />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.18, 12, 12]} />
        <meshBasicMaterial
          color="#FFE9B0" transparent opacity={0.35}
          depthWrite={false} blending={AdditiveBlending}
        />
      </mesh>
    </group>
  )
}

function Brackets() {
  const base = 'absolute w-3 h-3 border-[#3B9EFF]'
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
  const fleet     = useFleetPositions()
  const selected  = useTelemetryStore((s) => s.selectedSatIdx)
  const detail    = useTelemetryStore((s) => s.constellationDetail)
  const simTime   = useTelemetryStore((s) => s.sim_time_s)
  const sat       = fleet[selected]
  const timeScale = detail?.time_scale ?? 60

  const sunDir = useMemo(
    () => new Vector3(...eciToDisplay(SUN_DIR_ECI)).normalize(),
    [],
  )

  // GMST — same formula as services/constellations.py + useFleetPositions.
  // Earth rotation, sat orbital position, sunlit/eclipse all share this clock.
  const gmst = useMemo(
    () => (simTime * timeScale / SIDEREAL_DAY_S) * 2 * Math.PI,
    [simTime, timeScale],
  )

  const satPos = useMemo<[number, number, number] | null>(() => {
    if (!sat) return null
    const inv = 1 / EARTH_RADIUS_KM
    return eciToDisplay([sat.eci[0] * inv, sat.eci[1] * inv, sat.eci[2] * inv])
  }, [sat?.eci])

  const constellationId = detail?.id?.toUpperCase().replace(/_/g, '-') ?? 'STDBY'

  return (
    <div className="absolute left-3 bottom-3 z-10 pointer-events-none">
      <div className="pointer-events-auto relative h-[240px] w-[220px] bg-[#040912]/85 backdrop-blur-sm">
        {/* Faint cyan grid — holographic feel. */}
        <div
          className="absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              'linear-gradient(rgba(59,158,255,0.06) 1px, transparent 1px),'
              + 'linear-gradient(90deg, rgba(59,158,255,0.06) 1px, transparent 1px)',
            backgroundSize: '14px 14px',
          }}
        />
        <Brackets />

        {/* Header strip. */}
        <div className="absolute left-1.5 right-1.5 top-1.5 flex items-center justify-between">
          <span className="text-[8.5px] uppercase tracking-[0.20em] text-[#3B9EFF] font-mono">
            ▸ {constellationId}
          </span>
          <span
            className="text-[8.5px] uppercase tracking-[0.18em] font-mono"
            style={{ color: sat?.sunlit ? HUD_CYAN_HOT : HUD_WARN }}
          >
            {sat ? (sat.sunlit ? '◉ SUNLIT' : '○ ECLIPSE') : '— STDBY'}
          </span>
        </div>

        {/* Sub-header — selected sat + fleet shape. */}
        <div className="absolute left-1.5 right-1.5 top-[20px] flex items-center justify-between">
          <span className="text-[8px] tracking-[0.18em] text-[#3B9EFF]/80 font-mono">
            SAT-{String(selected).padStart(3, '0')}
          </span>
          <span className="text-[8px] tracking-[0.18em] text-[#3B9EFF]/80 font-mono">
            {detail ? `${detail.planes}P × ${detail.sats_per_plane}S` : ''}
          </span>
        </div>

        {/* 3D holographic scene. */}
        <div className="absolute inset-x-1 top-[36px] bottom-[52px]">
          <Canvas
            camera={{ position: [3.2, 1.9, 3.6], fov: 32 }}
            gl={{ antialias: true, alpha: true }}
          >
            <ambientLight intensity={0.4} />
            <GmstEarth gmst={gmst} />
            <MiniAtmosphere />
            {detail && detail.ring_eci_km.length > 0 && sat && (
              <ConstellationRings detail={detail} selectedPlane={sat.planeIdx} />
            )}
            {satPos && <SatReticle pos={satPos} />}
            <SunMarker dir={sunDir} />
          </Canvas>
        </div>

        {/* Footer telemetry — labelled mono readouts. */}
        <div className="absolute left-1.5 right-1.5 bottom-1.5 flex flex-col gap-[2px] text-[8.5px] font-mono leading-[1.3]">
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
