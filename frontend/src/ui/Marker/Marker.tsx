import type { Ref } from 'react'
import { Chip } from '@/ui/Chip'
import styles from './Marker.module.css'

interface MarkerProps {
  /** Accessible name and tag text (already translated). */
  label: string
  ref?: Ref<HTMLSpanElement>
}

/**
 * Generic ring with a centre dot, plus a leader line and name chip shown on hover.
 * The outer element is positioned by `placeMarker`; the inner parts react to hover. Hidden until placed.
 */
export function Marker({ label, ref }: MarkerProps) {
  return (
    <span ref={ref} className={styles.root} role="img" aria-label={label}>
      <span className={styles.ring} />
      <span className={styles.leader} aria-hidden="true">
        <span className={styles.diagonal} />
        <span className={styles.horizontal} />
        <span className={styles.tag}>
          <Chip className={styles.chip}>{label}</Chip>
        </span>
      </span>
    </span>
  )
}
