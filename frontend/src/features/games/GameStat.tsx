import { Icon } from '@/ui/Icon'
import styles from './Game.module.css'

interface GameStatProps {
  label: string
  value: string
  /** Small unit after the value. Symbols are not translated. */
  unit?: string
  /** Small text under the value, such as the safe limit. */
  note?: string
  /** Outside the safe range: shown inverted, with an icon and `overLabel` (never by colour alone). */
  over?: boolean
  overLabel?: string
}

/**
 * One HUD reading: label, large value and small unit. Its width is fixed, so the value changing never resizes
 * the reading. Plain text on the game screen, like the HUD of the reference.
 */
export function GameStat({ label, value, unit, note, over = false, overLabel }: GameStatProps) {
  return (
    <div className={styles.stat} data-over={over}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>
        {value}
        {unit && <span className={styles.statUnit}>{unit}</span>}
      </span>
      {(note || over) && (
        <span className={styles.statNote}>
          {over && <Icon name="alert" />}
          {over && overLabel ? `${overLabel}${note ? ` · ${note}` : ''}` : note}
        </span>
      )}
    </div>
  )
}
