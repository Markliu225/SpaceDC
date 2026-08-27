import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { useFleetStatuses } from '../../../hooks/useFleetStatuses'
import { useSmoothSimTime } from '../../../hooks/useSmoothSimTime'
import { satDisplayPosition, useConstellationRings } from './ringData'
import { colors } from '../../../design/tokens'

/**
 * Satellite billboards at the fleet's REAL propagated positions.
 *
 * Position comes from `ringData.satDisplayPosition` — the same polylines
 * `OrbitRibbons` draws, sampled at the satellite's Walker/SSO phase — so a
 * sprite can never float off its own ribbon. Identity and status come from
 * `useFleetStatuses` (the backend snapshot's online/eclipse/standby/offline
 * split over the propagated fleet). Nothing rides the render clock any more.
 *
 * Look is unchanged: radial-gradient sprite, hue = its plane's ribbon hue,
 * steady size; only the selected satellite pulses and gets an accent ring +
 * crosshair.
 */

/** Sprite budget. The big Walker presets fly 1500+ satellites, which is a lot
 *  of React elements for a decorative overview; the ribbons still show the full
 *  geometry, and the first N sats cover every plane because the fleet is
 *  ordered plane-major. */
const MAX_SPRITES = 256

export function Satellites() {
  const fleet       = useFleetStatuses()
  const selectedIdx = useTelemetryStore((s) => s.selectedSatIdx)
  const simTime     = useSmoothSimTime()
  const ringData    = useConstellationRings()

  const shown = useMemo(() => fleet.slice(0, MAX_SPRITES), [fleet])

  // Build a radial-gradient sprite texture once.
  const sprite = useMemo(() => makeRadialGradientTexture(64), [])
  useEffect(() => () => sprite.dispose(), [sprite])

  const groupRef = useRef<THREE.Group>(null!)

  useFrame((state) => {
    const g = groupRef.current
    if (!g) return
    // 1.4 s selection pulse — the one piece of motion that is meant to be
    // decorative; everything else moves because the physics says so.
    const pulse = 1.9 + 0.15 * Math.sin(state.clock.elapsedTime * ((Math.PI * 2) / 1.4))
    for (let i = 0; i < g.children.length; i++) {
      const child = g.children[i]
      const sat = shown[i]
      if (!sat) { child.visible = false; continue }
      const pos = satDisplayPosition(ringData, sat.idx, simTime)
      if (!pos) { child.visible = false; continue }
      child.visible = true
      child.position.set(pos[0], pos[1], pos[2])
      const isSelected = sat.idx === selectedIdx
      child.scale.setScalar(0.045 * (isSelected ? pulse * 1.2 : 1.9))
    }
  })

  // Memoised so the per-frame position pass above does not re-diff the whole
  // sprite list: this only rebuilds when the fleet or the selection changes.
  const sprites = useMemo(() => shown.map((sat) => (
    <group key={sat.id}>
      <sprite>
        <spriteMaterial
          map={sprite}
          // Same hue as the ribbon the sat rides (`planeIdx` is derived from
          // the same plane split OrbitRibbons uses).
          color={colors.ribbons[sat.planeIdx % colors.ribbons.length]}
          transparent
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </sprite>
      {sat.idx === selectedIdx && <SelectionRing color={colors.accent} />}
    </group>
  )), [shown, selectedIdx, sprite])

  return <group ref={groupRef} name="fleet-sprites">{sprites}</group>
}

/** A flat radial-gradient PNG, white core with a tight corona fading to transparent. */
function makeRadialGradientTexture(size: number): THREE.Texture {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  const g = ctx.createRadialGradient(size / 2, size / 2, 1, size / 2, size / 2, size / 2)
  g.addColorStop(0,    'rgba(255,255,255,1)')
  g.addColorStop(0.25, 'rgba(255,255,255,0.9)')
  g.addColorStop(0.45, 'rgba(255,255,255,0.12)')
  g.addColorStop(1,    'rgba(255,255,255,0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, size, size)
  const tex = new THREE.CanvasTexture(canvas)
  tex.needsUpdate = true
  return tex
}

/** Thin accent torus around the selected sat + axis-aligned crosshair lines. */
function SelectionRing({ color }: { color: string }) {
  const ringGeom = useMemo(() => new THREE.TorusGeometry(1.5, 0.08, 4, 48), [])
  useEffect(() => () => ringGeom.dispose(), [ringGeom])
  return (
    <group>
      <mesh geometry={ringGeom}>
        <meshBasicMaterial color={color} transparent opacity={0.85} toneMapped={false} />
      </mesh>
      {[
        [3, 0, 0],
        [-3, 0, 0],
        [0, 3, 0],
        [0, -3, 0],
      ].map((p, idx) => (
        <mesh key={idx} position={p as [number, number, number]} scale={[0.12, 0.12, 0.12]}>
          <boxGeometry />
          <meshBasicMaterial color={color} transparent opacity={0.85} toneMapped={false} />
        </mesh>
      ))}
    </group>
  )
}
