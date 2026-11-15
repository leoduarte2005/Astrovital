import type { Controls } from './useControls'
import styles from './Game.module.css'

export interface ControlButton {
  name: keyof Controls
  /** Accessible name (translated). */
  label: string
  /** Visible key glyph. */
  glyph: string
  /** Keyboard key shown under the glyph, when the glyph alone does not say it (translated). */
  keyHint?: string
}

interface GameControlsProps {
  buttons: ControlButton[]
  pressed: Controls
  hold: (name: keyof Controls) => Record<string, () => void>
}

/** On-screen controls. A held control, from touch or keyboard, is shown inverted. */
export function GameControls({ buttons, pressed, hold }: GameControlsProps) {
  return (
    <div className={styles.controls}>
      {buttons.map((button) => (
        <button
          key={button.name}
          type="button"
          className={styles.control}
          data-pressed={pressed[button.name]}
          aria-label={button.label}
          aria-pressed={pressed[button.name]}
          {...hold(button.name)}
        >
          <span className={styles.glyph} aria-hidden="true">
            {button.glyph}
          </span>
          {button.keyHint && (
            <span className={styles.keyHint} aria-hidden="true">
              {button.keyHint}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}
