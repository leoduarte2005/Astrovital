import { useEffect, useRef } from 'react'

export interface Controls {
  left: boolean
  right: boolean
  thrust: boolean
  fire: boolean
}

const KEYS: Record<string, keyof Controls> = {
  ArrowLeft: 'left',
  ArrowRight: 'right',
  ArrowUp: 'thrust',
  ' ': 'fire',
  Space: 'fire',
}

/**
 * Held controls from the keyboard. The on-screen buttons write to the same object, so touch and keyboard
 * behave alike. Read on every frame; never stored in React state.
 */
export function useControls(): { current: Controls } {
  const controls = useRef<Controls>({ left: false, right: false, thrust: false, fire: false })

  useEffect(() => {
    const set = (event: KeyboardEvent, pressed: boolean) => {
      const name = KEYS[event.key]
      if (!name) return
      event.preventDefault()
      controls.current[name] = pressed
    }
    const down = (event: KeyboardEvent) => set(event, true)
    const up = (event: KeyboardEvent) => set(event, false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

  return controls
}
