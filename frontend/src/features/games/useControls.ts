import { useCallback, useEffect, useRef, useState } from 'react'

export interface Controls {
  left: boolean
  right: boolean
  thrust: boolean
  fire: boolean
}

const NONE: Controls = { left: false, right: false, thrust: false, fire: false }

const KEYS: Record<string, keyof Controls> = {
  ArrowLeft: 'left',
  ArrowRight: 'right',
  ArrowUp: 'thrust',
  ' ': 'fire',
  Space: 'fire',
}

/**
 * Held controls from the keyboard and the on-screen buttons, which write to the same place.
 * `controls` is read by the game loop every frame. `pressed` is the same value as React state, changed
 * only when a control changes (not on key repeat), so the buttons can show which ones are held.
 * Everything is released when the window loses focus, so no key stays stuck.
 */
export function useControls() {
  const controls = useRef<Controls>({ ...NONE })
  const [pressed, setPressed] = useState<Controls>(NONE)

  const update = useCallback((name: keyof Controls, value: boolean) => {
    if (controls.current[name] === value) return
    controls.current = { ...controls.current, [name]: value }
    setPressed(controls.current)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent, value: boolean) => {
      const name = KEYS[event.key]
      if (!name) return
      event.preventDefault()
      update(name, value)
    }
    const down = (event: KeyboardEvent) => onKey(event, true)
    const up = (event: KeyboardEvent) => onKey(event, false)
    const releaseAll = () => {
      controls.current = { ...NONE }
      setPressed(controls.current)
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', releaseAll)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', releaseAll)
    }
  }, [update])

  /** Pointer handlers for an on-screen button that holds `name` while pressed. */
  const hold = useCallback(
    (name: keyof Controls) => ({
      onPointerDown: () => update(name, true),
      onPointerUp: () => update(name, false),
      onPointerLeave: () => update(name, false),
      onPointerCancel: () => update(name, false),
    }),
    [update],
  )

  return { controls, pressed, hold }
}
