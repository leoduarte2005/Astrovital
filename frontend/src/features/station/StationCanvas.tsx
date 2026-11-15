import { useEffect, useRef } from 'react'
import { useI18n } from '@/lib/i18n'
import { Marker } from '@/ui/Marker'
import { STATION_SECTIONS, type SectionId } from './anchors'
import { SENSOR_COLOR, STATION_SENSORS, sensorLocation } from './sensors'
import styles from './StationCanvas.module.css'

interface StationCanvasProps {
  /** True while a section is in focus (zoomed in), false when the view is back to the whole station. */
  onFocusChange?: (focused: boolean) => void
}

/**
 * Full-screen ISS model with its markers. It auto-rotates. The section markers (the junctions of the guide lines)
 * are clickable: a click focuses the section. The sensor markers appear only in focus and take no click.
 * Their chips show on hover. three.js loads on demand.
 */
export function StationCanvas({ onFocusChange }: StationCanvasProps) {
  const { t } = useI18n()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sectionRefs = useRef<Partial<Record<SectionId, HTMLElement | null>>>({})
  const sensorRefs = useRef<Partial<Record<string, HTMLElement | null>>>({})
  // Kept in a ref so a new callback does not remount the renderer.
  const onFocusChangeRef = useRef(onFocusChange)
  useEffect(() => {
    onFocusChangeRef.current = onFocusChange
  })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const markers: Partial<Record<SectionId, HTMLElement>> = {}
    for (const section of STATION_SECTIONS) {
      const element = sectionRefs.current[section.id]
      if (element) markers[section.id] = element
    }
    const sensors: Partial<Record<string, HTMLElement>> = {}
    for (const sensor of STATION_SENSORS) {
      const element = sensorRefs.current[sensor.id]
      if (element) sensors[sensor.id] = element
    }
    const controller = new AbortController()
    let dispose: (() => void) | undefined

    import('./renderer')
      .then(({ mount }) =>
        mount(canvas, {
          signal: controller.signal,
          markers,
          sensors,
          onSelect: (id) => onFocusChangeRef.current?.(id !== null),
        }),
      )
      .then(
        (renderer) => {
          // Unmounted while loading: release the GL objects right away.
          if (controller.signal.aborted) renderer.dispose()
          else dispose = renderer.dispose
        },
        (error: unknown) => {
          if (!controller.signal.aborted) console.warn('Station model failed to load', error)
        },
      )

    return () => {
      controller.abort()
      dispose?.()
    }
  }, [])

  return (
    <div className={styles.root}>
      <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />
      <div className={styles.markers}>
        {STATION_SECTIONS.map((section) => (
          <Marker
            key={section.id}
            label={section.name}
            ref={(element) => {
              sectionRefs.current[section.id] = element
            }}
          />
        ))}
        {STATION_SENSORS.map((sensor) => (
          <Marker
            key={sensor.id}
            label={`${t(`station.sensor.${sensor.kind}`)} · ${sensorLocation(sensor)}`}
            color={SENSOR_COLOR[sensor.kind]}
            clickable={false}
            ref={(element) => {
              sensorRefs.current[sensor.id] = element
            }}
          />
        ))}
      </div>
    </div>
  )
}
