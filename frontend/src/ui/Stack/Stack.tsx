import { Children, type CSSProperties, type ReactNode } from 'react'
import styles from './Stack.module.css'

interface StackProps {
  /** Accessible name of the list (already translated). */
  label: string
  /** Width of the stack; each item fills it. Any CSS length. */
  width?: string
  children: ReactNode
}

/** Vertical list of items with the same width and a gap between them. Each child gets its own list item. */
export function Stack({ label, width, children }: StackProps) {
  const style = width ? ({ width } as CSSProperties) : undefined
  return (
    <ul className={styles.root} style={style} aria-label={label}>
      {Children.map(children, (child) => (
        <li>{child}</li>
      ))}
    </ul>
  )
}
