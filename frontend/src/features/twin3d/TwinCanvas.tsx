import { useEffect, useRef, useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { Marker } from '@/ui/Marker'
import styles from './TwinCanvas.module.css'
import { TWIN_ANCHORS, type TwinAnchorId } from './anchors'
import { drawLeadLines } from './leadLines'
import type { TwinRenderer } from './renderer'

type Status = 'loading' | 'ready' | 'error'

/** Mounts the lazy three.js renderer on a canvas. The twin takes no pointer input. */
interface TwinCanvasProps {
  skinTone: string
  heightM: number
  onSelect?: (id: TwinAnchorId | null) => void
  /** Draws lead lines from every `data-lead` element on the page to its anchor (see leadLines.ts). Read at mount. */
  leadLines?: boolean
}

export function TwinCanvas({ skinTone, heightM, onSelect, leadLines = false }: TwinCanvasProps) {
  const { t } = useI18n()
  const leadLinesRef = useRef(leadLines)
  const linePathRef = useRef<SVGPathElement>(null)
  const dotPathRef = useRef<SVGPathElement>(null)
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
          onSelect: (id) => onSelectRef.current?.(id),
          onProject: leadLinesRef.current
            ? (points) => {
                const lines = linePathRef.current
                const dots = dotPathRef.current
                if (lines && dots) drawLeadLines(lines, dots, points)
              }
            : undefined,
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
      {leadLines && (
        <svg className={styles.leads} aria-hidden="true">
          <path ref={linePathRef} className={styles.leadLine} />
          <path ref={dotPathRef} className={styles.leadDot} />
        </svg>
      )}
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
