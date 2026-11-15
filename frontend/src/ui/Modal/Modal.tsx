import { useEffect, useId, useRef, type ReactNode } from 'react'
import { IconButton } from '@/ui/IconButton'
import styles from './Modal.module.css'

interface ModalProps {
  size: 'xl' | 'full'
  /** Shown at the top, on the same row as the close button. Also the dialog's accessible name. */
  title: string
  closeLabel: string
  onClose: () => void
  children: ReactNode
}

/** Native modal dialog: opens on mount, closes on Esc or the close button, reports every close to `onClose`. */
export function Modal({ size, title, closeLabel, onClose, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog || dialog.open) return
    dialog.showModal()
  }, [])

  return (
    <dialog ref={ref} className={`${styles.root} ${styles[size]}`} aria-labelledby={titleId} onClose={onClose}>
      <header className={styles.header}>
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        <IconButton icon="close" label={closeLabel} onClick={() => ref.current?.close()} />
      </header>
      {children}
    </dialog>
  )
}
