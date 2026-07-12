import { useEffect, useRef, useState } from 'react'
import { useTelemetryStore } from '../store/useTelemetryStore'

/**
 * useSmoothSimTime — a smoothly-extrapolated copy of the shared sim clock.
 *
 * The store's `sim_time_s` advances in 1 s steps (backend broadcasts at
 * 1 Hz), which makes anything animated directly from it JUMP once per
 * second — at the demo's 60× orbit time-scale a LEO satellite marker leaps
 * ~6.5° of orbit per jump and reads as broken/static. This hook anchors on
 * every store update and extrapolates between them at the sim rate
 * (1 sim-s per wall-s) via requestAnimationFrame, so orbit markers glide.
 *
 * Re-anchoring snaps cleanly on backend restarts / resets (sim jumps back).
 */
export function useSmoothSimTime(): number {
  const [smooth, setSmooth] = useState(() => useTelemetryStore.getState().sim_time_s)
  const anchorRef = useRef<{ sim: number; wall: number } | null>(null)

  useEffect(() => {
    anchorRef.current = {
      sim: useTelemetryStore.getState().sim_time_s,
      wall: performance.now(),
    }
    const unsub = useTelemetryStore.subscribe((s, prev) => {
      if (s.sim_time_s !== prev.sim_time_s) {
        anchorRef.current = { sim: s.sim_time_s, wall: performance.now() }
      }
    })
    let raf = 0
    const tick = () => {
      const a = anchorRef.current
      if (a) setSmooth(a.sim + (performance.now() - a.wall) / 1000)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { unsub(); cancelAnimationFrame(raf) }
  }, [])

  return smooth
}
