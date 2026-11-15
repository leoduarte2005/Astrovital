import { useEffect } from 'react'
import styles from './AlertBadge.module.css'

interface AlertBadgeProps {
  /** Already translated. */
  message: string
  onDismiss: () => void
  /** How long it stays before it goes away on its own. */
  durationMs?: number
}

/** Short notice in the bottom-right corner. Announced politely; dismisses itself. */
export function AlertBadge({ message, onDismiss, durationMs = 4000 }: AlertBadgeProps) {
  useEffect(() => {
    const id = window.setTimeout(onDismiss, durationMs)
    return () => window.clearTimeout(id)
  }, [message, durationMs, onDismiss])

  return (
    <div className={styles.root} role="status" aria-live="polite">
      {message}
    </div>
  )
}
