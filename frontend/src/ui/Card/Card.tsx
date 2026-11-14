import type { ReactNode } from 'react'
import styles from './Card.module.css'

interface CardProps {
  children: ReactNode
  /** Renders a link. */
  href?: string
  /** Renders a button. */
  onClick?: () => void
  /** Accessible name for interactive cards whose content is not self-describing. */
  label?: string
}

/** Surface container. Plain `div`, or an interactive link/button when `href`/`onClick` is given. */
export function Card({ children, href, onClick, label }: CardProps) {
  if (href !== undefined) {
    return (
      <a className={`${styles.root} ${styles.interactive}`} href={`#${href}`} aria-label={label}>
        {children}
      </a>
    )
  }
  if (onClick) {
    return (
      <button type="button" className={`${styles.root} ${styles.interactive}`} aria-label={label} onClick={onClick}>
        {children}
      </button>
    )
  }
  return <div className={styles.root}>{children}</div>
}
