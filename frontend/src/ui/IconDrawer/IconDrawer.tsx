import { useEffect } from 'react'
import { type IconName } from '@/ui/Icon'
import { IconButton } from '@/ui/IconButton'
import styles from './IconDrawer.module.css'

export interface IconDrawerItem {
  key: string
  icon: IconName
  /** Accessible name and tooltip text (already translated). */
  label: string
  onSelect: () => void
}

interface IconDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Icon of the trigger while closed; it becomes "close" while open. */
  icon: IconName
  openLabel: string
  closeLabel: string
  items: IconDrawerItem[]
}

/**
 * Icon-only trigger that opens a horizontal drawer to its left. The drawer slides with
 * `transform` and `opacity` only. Esc closes it; the trigger toggles it.
 */
export function IconDrawer({ open, onOpenChange, icon, openLabel, closeLabel, items }: IconDrawerProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onOpenChange(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  return (
    <div className={styles.root}>
      <div className={[styles.panel, open ? styles.panelOpen : ''].filter(Boolean).join(' ')} aria-hidden={!open}>
        {items.map((item) => (
          <IconButton key={item.key} icon={item.icon} label={item.label} onClick={item.onSelect} />
        ))}
      </div>
      <IconButton
        icon={open ? 'close' : icon}
        label={open ? closeLabel : openLabel}
        expanded={open}
        onClick={() => onOpenChange(!open)}
      />
    </div>
  )
}
