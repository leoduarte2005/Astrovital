import type { ReactNode, RefObject } from 'react'
import { useI18n } from '@/lib/i18n'
import { IconButton } from '@/ui/IconButton'
import styles from './ChartFrame.module.css'

interface ChartFrameProps {
  title: string
  unit: string
  valueRef: RefObject<HTMLSpanElement | null>
  /** Informative text shown instead of the plot (no data, connecting, offline). Null shows the plot. */
  message: string | null
  /** Opens the chart in the large view. Omit inside that view. */
  onExpand?: () => void
  /** Inside the modal the title is already shown by the dialog header: only the value and plot remain. */
  expanded?: boolean
  children: ReactNode
}

/** Card around a chart: title with a compact expand button, the latest value (large; unit small on the baseline), message or plot. */
export function ChartFrame({ title, unit, valueRef, message, onExpand, expanded = false, children }: ChartFrameProps) {
  const { t } = useI18n()
  return (
    <section className={expanded ? `${styles.root} ${styles.expanded}` : styles.root} aria-label={title}>
      {!expanded && (
        <header className={styles.header}>
          <h3 className={styles.title}>{title}</h3>
          {onExpand && <IconButton icon="expand" label={t('chart.expand')} onClick={onExpand} size="sm" iconSize="sm" />}
        </header>
      )}
      <p className={styles.value}>
        <span ref={valueRef}>—</span>
        <span className={styles.unit}>{unit}</span>
      </p>
      {message !== null && <p className={styles.message}>{message}</p>}
      {children}
    </section>
  )
}
