import type { ReactNode } from 'react'
import { Icon, type IconName } from '@/ui/Icon'
import styles from './Button.module.css'

interface ButtonProps {
  onClick: () => void
  variant?: 'solid' | 'ghost'
  icon?: IconName
  /** Required when there are no children (icon-only button). */
  label?: string
  children?: ReactNode
}

export function Button({ onClick, variant = 'ghost', icon, label, children }: ButtonProps) {
  const isIconOnly = children === undefined
  return (
    <button
      type="button"
      className={`${styles.root} ${styles[variant]} ${isIconOnly ? styles.iconOnly : ''}`}
      aria-label={isIconOnly ? label : undefined}
      onClick={onClick}
    >
      {icon && <Icon name={icon} />}
      {children}
    </button>
  )
}
