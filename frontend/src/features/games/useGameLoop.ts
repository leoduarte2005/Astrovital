import { useEffect, useRef } from 'react'

/** Longest step in seconds: a slow frame does not make the game jump. */
const MAX_STEP = 0.05

/**
 * Calls `onFrame(dt)` on every animation frame. Stops while the page is hidden, and does not catch up when
 * it comes back. The callback is kept in a ref, so a new callback does not restart the loop.
 */
export function useGameLoop(onFrame: (dt: number) => void): void {
  const callback = useRef(onFrame)
  useEffect(() => {
    callback.current = onFrame
  })

  useEffect(() => {
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(MAX_STEP, (now - last) / 1000)
      last = now
      if (document.visibilityState === 'visible') callback.current(dt)
      frame = requestAnimationFrame(tick)
    }
    const onVisibility = () => {
      last = performance.now()
    }
    frame = requestAnimationFrame(tick)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])
}
