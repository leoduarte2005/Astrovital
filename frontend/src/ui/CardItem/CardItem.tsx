import type { ReactNode } from 'react'
import { Card } from '@/ui/Card'
import { Icon, type IconName } from '@/ui/Icon'
import styles from './CardItem.module.css'

interface CardItemProps {
  /** Main text of the card (already translated, or data). */
  title: string
  /** Leading icon in a round frame. */
  icon?: IconName
  /** Right-hand content, e.g. a Readout. */
  trailing?: ReactNode
  /** Makes the card a button. Without it, the card is static. */
  onClick?: () => void
  /** Accessible name for interactive cards (defaults to the title). */
  label?: string
}

/** Surface card in a row: optional icon, title, and trailing content. Fills the width it is placed in. */
export function CardItem({ title, icon, trailing, onClick, label }: CardItemProps) {
  return (
    <Card onClick={onClick} label={onClick ? (label ?? title) : undefined}>
      <div className={styles.row}>
        {icon && (
          <span className={styles.avatar} aria-hidden="true">
            <Icon name={icon} />
          </span>
        )}
        <span className={styles.title}>{title}</span>
        {trailing && <span className={styles.trailing}>{trailing}</span>}
      </div>
    </Card>
  )
}
