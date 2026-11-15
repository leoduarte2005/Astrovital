import type { CSSProperties, ReactNode } from 'react'
import styles from './GridBackdrop.module.css'

interface GridBackdropProps {
  children: ReactNode
  /** Size of one grid cell, any CSS length. Default 48px. */
  cell?: string
  /** Shows the grid. Off, only the page background remains. Default on. */
  grid?: boolean
}

/** Fills its box with the page background and a light grid. Content sits on top. */
export function GridBackdrop({ children, cell, grid = true }: GridBackdropProps) {
  const style = cell ? ({ '--grid-cell': cell } as CSSProperties) : undefined
  return (
    <div className={styles.root} style={style} data-grid={grid}>
      {children}
    </div>
  )
}
