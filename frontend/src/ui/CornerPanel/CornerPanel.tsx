import type { ReactNode } from 'react'
import styles from './CornerPanel.module.css'

export type Corner = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'

const CORNER_CLASS: Record<Corner, string | undefined> = {
  'top-left': styles.topLeft,
  'top-right': styles.topRight,
  'bottom-left': styles.bottomLeft,
  'bottom-right': styles.bottomRight,
}

interface CornerPanelProps {
  corner: Corner
  children: ReactNode
  /** Hides the panel without unmounting it (its children keep running, e.g. live feeds). */
  hidden?: boolean
}

/** Absolutely placed panel in one corner of its positioned parent, on top of the content behind it. */
export function CornerPanel({ corner, children, hidden = false }: CornerPanelProps) {
  return (
    <div className={`${styles.root} ${CORNER_CLASS[corner] ?? ''}`} hidden={hidden}>
      {children}
    </div>
  )
}
