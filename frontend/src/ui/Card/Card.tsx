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
  /** Layout from the caller (size, proportion). The card's own look stays in the kit. */
  className?: string
}

/** Surface container. Plain `div`, or an interactive link/button when `href`/`onClick` is given. */
export function Card({ children, href, onClick, label, className }: CardProps) {
  const base = className ? `${styles.root} ${className}` : styles.root
  if (href !== undefined) {
    return (
      <a className={`${base} ${styles.interactive}`} href={`#${href}`} aria-label={label}>
        {children}
      </a>
    )
  }
  if (onClick) {
    return (
      <button type="button" className={`${base} ${styles.interactive}`} aria-label={label} onClick={onClick}>
        {children}
      </button>
    )
  }
  return <div className={base}>{children}</div>
}
