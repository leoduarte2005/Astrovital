import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { mountAstronaut } from './renderer'
import styles from './AstronautViewer.module.css'

interface AstronautViewerProps {
  /** Accessible name of the model (translated, with the member's name). */
  label: string
}

/** The crew member's astronaut model, as it is in the GLB, framed in its box. The three.js renderer loads only here. */
export function AstronautViewer({ label }: AstronautViewerProps) {
  const { t } = useI18n()
  const hostRef = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let alive = true
    let dispose: (() => void) | null = null
    mountAstronaut(host)
      .then((disposeScene) => {
        // Unmounted while the model was loading: release it at once.
        if (alive) dispose = disposeScene
        else disposeScene()
      })
      .catch((error) => {
        console.warn('astronaut model failed', error)
        if (alive) setFailed(true)
      })
    return () => {
      alive = false
      dispose?.()
    }
  }, [])

  return (
    <div ref={hostRef} className={styles.root} role="img" aria-label={label}>
      {failed && <p className={styles.error}>{t('astronaut.viewer.error')}</p>}
    </div>
  )
}
