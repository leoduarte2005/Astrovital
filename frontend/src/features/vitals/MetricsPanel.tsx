import { useEffect, useMemo, useRef } from 'react'
import { useBaseline, useHistory } from '@/lib/data/useBaseline'
import { useI18n } from '@/lib/i18n'
import { navigate } from '@/lib/utils/hashRoute'
import {
  BASELINE_METRICS,
  corridorState,
  type BaselineMetricSpec,
  type BaselineProfile,
  type Corridor,
  type CorridorState,
} from '@/lib/model/baseline'
import { Button } from '@/ui/Button'
import { ExpandableChart } from '@/ui/Chart'
import { Icon } from '@/ui/Icon'
import { IconButton } from '@/ui/IconButton'
import { vitalFeed } from './vitalFeed'
import styles from './MetricsPanel.module.css'

/** The sleep metric has no live feed: its value is the last night of the week window. */
const LIVE_METRICS = new Set(['heartRate', 'hrv', 'respRate', 'spo2'])

/** Minimised card of the home: the five baseline metrics at a glance. Expands to a near full-screen view. */
export function MetricsPanel() {
  const { t } = useI18n()
  const baseline = useBaseline()
  const sleepLast = useHistory('sleep', 'week')?.y.at(-1) ?? null
  return (
    <ExpandableChart
      title={t('metrics.title')}
      size="full"
      renderChart={(expanded, onExpand) => (
        <section className={expanded ? `${styles.root} ${styles.expanded}` : styles.root} aria-label={t('metrics.title')}>
          {!expanded && (
            <header className={styles.header}>
              <h3 className={styles.title}>{t('metrics.title')}</h3>
              {onExpand && <IconButton icon="expand" label={t('chart.expand')} onClick={onExpand} size="sm" iconSize="sm" />}
            </header>
          )}
          <ul className={styles.list}>
            {BASELINE_METRICS.map((spec) => (
              <MetricRow key={spec.id} spec={spec} corridor={baseline?.corridors[spec.id] ?? null} sleepLast={sleepLast} />
            ))}
          </ul>
          {expanded && baseline && <TrainingNote baseline={baseline} />}
        </section>
      )}
    />
  )
}

function TrainingNote({ baseline }: { baseline: BaselineProfile }) {
  const { t, locale } = useI18n()
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' })
  const { training } = baseline
  return (
    <div className={styles.note}>
      <p>{t('charts.baseline.period', { from: date.format(training.trainedFrom), to: date.format(training.trainedTo) })}</p>
      <p>{t('charts.baseline.days', { days: training.days, expected: training.expectedDays })}</p>
      <p>{t('charts.baseline.note')}</p>
      <Button onClick={() => navigate('/charts')}>{t('metrics.openCharts')}</Button>
    </div>
  )
}

interface RowProps {
  spec: BaselineMetricSpec
  corridor: Corridor | null
  /** Last night's sleep, for the sleep row (no live feed). */
  sleepLast: number | null
}

function MetricRow({ spec, corridor, sleepLast: night }: RowProps) {
  const { t, locale } = useI18n()
  const valueRef = useRef<HTMLSpanElement>(null)
  const chipRef = useRef<HTMLSpanElement>(null)
  const live = LIVE_METRICS.has(spec.id)

  const number = useMemo(
    () => new Intl.NumberFormat(locale, { minimumFractionDigits: spec.decimals, maximumFractionDigits: spec.decimals }),
    [locale, spec.decimals],
  )

  // Live values change several times a second: written straight to the DOM, never through React state.
  useEffect(() => {
    if (!live) return
    const feed = vitalFeed.lineFeed(spec.id)
    const apply = () => {
      const { y } = feed.read()
      const last = y.at(-1) ?? null
      if (valueRef.current) valueRef.current.textContent = last === null ? '—' : number.format(last)
      if (chipRef.current) chipRef.current.dataset.state = last === null || !corridor ? 'none' : corridorState(last, corridor)
    }
    apply()
    return feed.subscribe(apply)
  }, [live, spec.id, corridor, number])

  const sleepLast = spec.id === 'sleep' ? night : null
  const staticState: CorridorState | 'none' = sleepLast !== null && corridor ? corridorState(sleepLast, corridor) : 'none'

  return (
    <li className={styles.row}>
      <span className={styles.label}>{t(spec.labelKey)}</span>
      <span className={styles.value}>
        <span ref={valueRef}>{live ? '—' : sleepLast === null ? '—' : number.format(sleepLast)}</span>
        <span className={styles.unit}>{spec.unit}</span>
      </span>
      <span ref={chipRef} className={styles.chip} data-state={live ? 'none' : staticState}>
        <span className={styles.alert}>
          <Icon name="alert" />
        </span>
        <span data-s="inside">{t('corridor.inside')}</span>
        <span data-s="below">{t('corridor.below')}</span>
        <span data-s="above">{t('corridor.above')}</span>
      </span>
      {corridor && (
        <span className={styles.base}>
          {t('metrics.base', { value: number.format(corridor.mean) })} ·{' '}
          {t('metrics.corridor', { low: number.format(corridor.low), high: number.format(corridor.high) })}
          {spec.id === 'sleep' ? ` · ${t('metrics.sleepNight')}` : ''}
        </span>
      )}
    </li>
  )
}
