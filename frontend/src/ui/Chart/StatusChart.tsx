import { memo, useEffect, useRef, type RefObject } from 'react'
import type { ChartFeed, LineSnapshot } from './types'
import styles from './StatusChart.module.css'

export interface StatusChartProps {
  title: string
  feed: ChartFeed<LineSnapshot>
  message: string | null
  valueFormat: (value: number) => string
  kind: 'severity' | 'category'
}

interface StatusCardProps extends StatusChartProps {
  valueRef: RefObject<HTMLSpanElement | null>
  rootRef: RefObject<HTMLElement | null>
}

function statusClass(kind: StatusChartProps['kind'], value: number | null): string {
  if (kind !== 'severity' || value === null) return styles.neutral!
  if (value === 0) return styles.ok!
  if (value === 1) return styles.warn!
  return styles.high!
}

function StatusCard({ title, feed, message, valueFormat, kind, valueRef, rootRef }: StatusCardProps) {
  const snapshot = feed.read()
  const value = snapshot.y[snapshot.y.length - 1] ?? null
  const valueText = value === null ? '—' : valueFormat(value)

  return (
    <section ref={rootRef} className={`${styles.root} ${statusClass(kind, value)}`} aria-label={title}>
      <h3 className={styles.title}>{title}</h3>
      <p className={styles.value}>
        <span ref={valueRef}>{valueText}</span>
      </p>
      {message !== null && <p className={styles.message}>{message}</p>}
    </section>
  )
}

/** Compact live indicator for categorical and severity values. */
export const StatusChart = memo(function StatusChart(props: StatusChartProps) {
  const { feed, valueFormat, kind } = props
  const valueRef = useRef<HTMLSpanElement>(null)
  const rootRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const update = () => {
      const snapshot = feed.read()
      const value = snapshot.y[snapshot.y.length - 1] ?? null
      if (valueRef.current) valueRef.current.textContent = value === null ? '—' : valueFormat(value)
      if (rootRef.current) rootRef.current.className = `${styles.root} ${statusClass(kind, value)}`
    }

    update()
    return feed.subscribe(update)
  }, [feed, kind, valueFormat])

  return <StatusCard {...props} valueRef={valueRef} rootRef={rootRef} />
})
