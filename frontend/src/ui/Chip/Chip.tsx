import type { CSSProperties, ReactNode } from 'react'
import { Icon, type IconName } from '@/ui/Icon'
import styles from './Chip.module.css'

interface ChipProps {
  children: ReactNode
  icon?: IconName
  dot?: string
  /** Filled with the accent colour instead of the outlined default. */
  solid?: boolean
  className?: string
}

export function Chip({ children, icon, dot, solid = false, className }: ChipProps) {
  const classes = [styles.root, solid ? styles.solid : '', className ?? ''].filter(Boolean).join(' ')
  return (
    <span className={classes}>
      {dot && <span className={styles.dot} style={{ '--chip-dot': dot } as CSSProperties} aria-hidden="true" />}
      {icon && <Icon name={icon} />}
      {children}
    </span>
  )
}
