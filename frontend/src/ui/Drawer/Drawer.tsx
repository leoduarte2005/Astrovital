import { useEffect, type ReactNode } from 'react'
import { Icon, type IconName } from '@/ui/Icon'
import { IconButton } from '@/ui/IconButton'
import styles from './Drawer.module.css'

interface DrawerExpand {
  expanded: boolean
  onExpandedChange: (expanded: boolean) => void
  expandLabel: string
  collapseLabel: string
}

interface DrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  openLabel: string
  closeLabel: string
  icon: IconName
  /** Optional full-width toggle in the header. Esc also collapses. */
  expand?: DrawerExpand
  children: ReactNode
}

/** Narrow side drawer anchored to the right edge. Slides with `transform` only. */
export function Drawer({ open, onOpenChange, title, openLabel, closeLabel, icon, expand, children }: DrawerProps) {
  const expanded = expand?.expanded ?? false
  const onExpandedChange = expand?.onExpandedChange

  useEffect(() => {
    if (!expanded || !onExpandedChange) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onExpandedChange(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded, onExpandedChange])

  const tabClass = [styles.tab, open ? styles.tabOpen : '', open && expanded ? styles.tabExpanded : '']
  const panelClass = [styles.panel, open ? styles.panelOpen : '', open && expanded ? styles.panelExpanded : '']

  return (
    <>
      <button
        type="button"
        className={tabClass.filter(Boolean).join(' ')}
        aria-label={open ? closeLabel : openLabel}
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
      >
        <Icon name={open ? 'close' : icon} />
      </button>
      <aside className={panelClass.filter(Boolean).join(' ')} aria-label={title} aria-hidden={!open}>
        <div className={styles.header}>
          <h2 className={styles.title}>{title}</h2>
          {expand && (
            <IconButton
              icon={expand.expanded ? 'collapse' : 'expand'}
              label={expand.expanded ? expand.collapseLabel : expand.expandLabel}
              onClick={() => expand.onExpandedChange(!expand.expanded)}
            />
          )}
        </div>
        <div className={styles.body}>{children}</div>
      </aside>
    </>
  )
}
