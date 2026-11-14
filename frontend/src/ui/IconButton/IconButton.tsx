import { Icon, type IconName } from '@/ui/Icon'
import styles from './IconButton.module.css'

interface IconButtonProps {
  icon: IconName
  /** Accessible name and tooltip text (already translated). */
  label: string
  onClick: () => void
  disabled?: boolean
}

/** Round icon-only button; the label shows as a tooltip on hover and keyboard focus. */
export function IconButton({ icon, label, onClick, disabled = false }: IconButtonProps) {
  return (
    <button type="button" className={styles.root} aria-label={label} onClick={onClick} disabled={disabled}>
      <Icon name={icon} />
      <span className={styles.tooltip} aria-hidden="true">
        {label}
      </span>
    </button>
  )
}
