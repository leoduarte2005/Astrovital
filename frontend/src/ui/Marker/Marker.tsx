import type { CSSProperties, Ref } from 'react'
import { Chip } from '@/ui/Chip'
import styles from './Marker.module.css'

interface MarkerProps {
  /** Accessible name and tag text (already translated). */
  label: string
  /** Colour of the ring, leader and chip border. Default: the kit's --ink. */
  color?: string
  /** False for presentation only: no pointer cursor (the element still shows its chip on hover). Default true. */
  clickable?: boolean
  ref?: Ref<HTMLSpanElement>
}

/**
 * Generic ring with a centre dot, plus a leader line and name chip shown on hover.
 * The outer element is positioned by `placeMarker`; the inner parts react to hover. Hidden until placed.
 */
export function Marker({ label, color, clickable = true, ref }: MarkerProps) {
  const style = color ? ({ '--marker-color': color } as CSSProperties) : undefined
  const classes = [styles.root, clickable ? '' : styles.passive].filter(Boolean).join(' ')
  return (
    <span ref={ref} className={classes} style={style} role="img" aria-label={label}>
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
