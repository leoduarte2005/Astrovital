import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { Marker } from '@/ui/Marker'
import styles from './TwinCanvas.module.css'
import { TWIN_ANCHORS, type TwinAnchorId } from './anchors'
import type { TwinRenderer } from './renderer'

type Status = 'loading' | 'ready' | 'error'

/** Mounts the lazy three.js renderer on a canvas. The twin takes no pointer input. */
interface TwinCanvasProps {
  skinTone: string
  heightM: number
  onSelect?: (id: TwinAnchorId | null) => void
  /** Plays the suit-fragmentation intro when the twin mounts. Read once, at mount: changing it later does not replay. */
  intro?: boolean
}

export function TwinCanvas({ skinTone, heightM, onSelect, intro = false }: TwinCanvasProps) {
  const { t } = useI18n()
  const introRef = useRef(intro)
  // Kept in a ref so a new callback does not remount the renderer.
  const onSelectRef = useRef(onSelect)
  useEffect(() => {
    onSelectRef.current = onSelect
  })
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const markerRefs = useRef<Partial<Record<TwinAnchorId, HTMLElement | null>>>({})
  const [status, setStatus] = useState<Status>('loading')

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const markers: Partial<Record<TwinAnchorId, HTMLElement>> = {}
    for (const anchor of TWIN_ANCHORS) {
      const element = markerRefs.current[anchor.id]
      if (element) markers[anchor.id] = element
    }
    // The signal stops a stale mount (StrictMode, tone change) before it creates a second
    // WebGL renderer on the same canvas, which would corrupt the shared GL context.
    const controller = new AbortController()
    let handle: TwinRenderer | null = null

    import('./renderer')
      .then((module) =>
        module.mount(canvas, {
          skinTone,
          heightM,
          signal: controller.signal,
          markers,
          intro: introRef.current,
          onSelect: (id) => onSelectRef.current?.(id),
        }),
      )
      .then((renderer) => {
        if (controller.signal.aborted) {
          renderer.dispose()
          return
        }
        handle = renderer
        setStatus('ready')
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        console.warn('Digital twin failed to load', error)
        setStatus('error')
      })

    return () => {
      controller.abort()
      handle?.dispose()
    }
  }, [skinTone, heightM])

  return (
    <div className={styles.root}>
      <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />
      {TWIN_ANCHORS.map((anchor) => (
        <Marker
          key={anchor.id}
          label={t(anchor.labelKey)}
          ref={(element) => {
            markerRefs.current[anchor.id] = element
          }}
        />
      ))}
      {status === 'loading' && <p className={styles.status}>{t('common.loading')}</p>}
      {status === 'error' && <p className={styles.status}>{t('home.twin.error')}</p>}
    </div>
  )
}
