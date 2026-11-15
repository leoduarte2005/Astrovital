import type { Ref } from 'react'
import styles from './Readout.module.css'

interface ReadoutProps {
  /** Shown until a value is written (the placeholder). */
  value?: string
  /** Unit after the value (already translated). */
  unit?: string
  /** Tooltip (already translated). */
  title?: string
  /** Lets a caller write the value straight to the DOM, without React state (for high-frequency streams). */
  valueRef?: Ref<HTMLSpanElement>
}

/** A numeric value with its unit. Tabular figures, so changing values do not shift the layout. */
export function Readout({ value = '--', unit, title, valueRef }: ReadoutProps) {
  return (
    <span className={styles.root} title={title}>
      <span ref={valueRef} className={styles.value}>
        {value}
      </span>
      {unit && <span className={styles.unit}>{unit}</span>}
    </span>
  )
}
