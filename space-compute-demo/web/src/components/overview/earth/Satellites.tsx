import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useTelemetryStore } from '../../../store/useTelemetryStore'
import { ribbonPosition } from './OrbitRibbons'
import { colors } from '../../../design/tokens'

/**
 * 24 satellite billboards, each a radial-gradient sprite. Color matches the
 * ribbon hue; size is steady (1.9x) — only the selected sat pulses gently
 * with a 1.4s sine and gets a 2px accent ring + crosshair.
 */
export function Satellites() {
  const sats         = useTelemetryStore((s) => s.sats)
  const selectedId   = useTelemetryStore((s) => s.selectedId)

  // Build a radial-gradient sprite texture once.
  const sprite = useMemo(() => makeRadialGradientTexture(64), [])

  const groupRef = useRef<THREE.Group>(null!)
  const simRef   = useRef(0)

  useFrame((state, dt) => {
    simRef.current = state.clock.elapsedTime
    if (!groupRef.current) return
    const pulse = 1.9 + 0.15 * Math.sin(simRef.current * (Math.PI * 2 / 1.4))
    groupRef.current.children.forEach((child, i) => {
      const sat = sats[i]
      if (!sat) return
      const pos = ribbonPosition(i, sats.length, simRef.current)
      child.position.copy(pos)
      // Constant world scale for billboards.
      const isSelected = sat.id === selectedId
      const s = 0.045 * (isSelected ? pulse * 1.2 : 1.9)
      child.scale.setScalar(s)
      // Cheap unused-var nudge to silence noUnusedParameters lints.
      void dt
    })
  })

  return (
    <group ref={groupRef}>
      {sats.map((sat, i) => {
        const color = colors.ribbons[i % 6]
        const isSelected = sat.id === selectedId
        return (
          <group key={sat.id}>
            <sprite>
              <spriteMaterial
                map={sprite}
                color={color}
                transparent
                blending={THREE.AdditiveBlending}
                depthWrite={false}
                toneMapped={false}
              />
            </sprite>
            {isSelected && <SelectionRing color={colors.accent} />}
          </group>
        )
      })}
    </group>
  )
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
