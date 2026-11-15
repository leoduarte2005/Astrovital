import { useMemo, useState } from 'react'
import { useBaseline, useHistory } from '@/lib/data/useBaseline'
import { useI18n, type MessageKey } from '@/lib/i18n'
import {
  BASELINE_METRICS,
  corridorState,
  deviationPercent,
  type BaselineMetricSpec,
  type CorridorState,
  type HistoryWindow,
} from '@/lib/model/baseline'
import { CorridorChart, ExpandableChart } from '@/ui/Chart'
import { SegmentedControl } from '@/ui/SegmentedControl'
import { BaselineSummary } from './BaselineSummary'
import styles from './LongitudinalCharts.module.css'

const WINDOWS: HistoryWindow[] = ['day', 'week', 'mission', 'preflight']

const WINDOW_LABEL: Record<HistoryWindow, MessageKey> = {
  day: 'charts.window.day',
  week: 'charts.window.week',
  mission: 'charts.window.mission',
  preflight: 'charts.window.preflight',
}

const STATE_LABEL: Record<CorridorState, MessageKey> = {
  inside: 'corridor.inside',
  below: 'corridor.below',
  above: 'corridor.above',
}

const SUMMARY_KEY: Record<CorridorState, MessageKey> = {
  inside: 'charts.summary.inside',
  below: 'charts.summary.below',
  above: 'charts.summary.above',
}

/** The x axis label for each window: clock time for a day, day and month for weeks, month and year for years. */
function dateFormat(window: HistoryWindow): Intl.DateTimeFormatOptions {
  if (window === 'day') return { hour: '2-digit', minute: '2-digit' }
  if (window === 'preflight') return { month: 'short', year: '2-digit' }
  return { day: '2-digit', month: 'short' }
}

/** Every baseline metric against the crew member's own corridor, over the window chosen at the top. */
export function LongitudinalCharts() {
  const { t } = useI18n()
  const [window, setWindow] = useState<HistoryWindow>('mission')
  const baseline = useBaseline()

  const options = WINDOWS.map((value) => ({
    value,
    label: t(WINDOW_LABEL[value]),
  }))

  return (
    <div className={styles.root}>
      <SegmentedControl label={t('charts.window.label')} options={options} value={window} onChange={setWindow} />
      <div className={styles.grid}>
        {BASELINE_METRICS.map((spec) => (
          <MetricChart key={spec.id} spec={spec} window={window} />
        ))}
      </div>
      {baseline && <BaselineSummary training={baseline.training} />}
    </div>
  )
}

function MetricChart({ spec, window }: { spec: BaselineMetricSpec; window: HistoryWindow }) {
  const { t, locale } = useI18n()
  const series = useHistory(spec.id, window)
  const number = useMemo(
    () =>
      new Intl.NumberFormat(locale, {
        minimumFractionDigits: spec.decimals,
        maximumFractionDigits: spec.decimals,
      }),
    [locale, spec.decimals],
  )
  const xFormat = useMemo(() => {
    const format = new Intl.DateTimeFormat(locale, dateFormat(window)).format
    return (seconds: number) => format(new Date(seconds * 1000))
  }, [locale, window])

  if (!series) return <p className={styles.loading}>{t('common.loading')}</p>

  const label = t(spec.labelKey)
  const { corridor } = series
  const mean = series.y.length ? series.y.reduce((sum, value) => sum + value, 0) / series.y.length : corridor.mean
  const state = corridorState(mean, corridor)
  const format = (value: number) => number.format(value)

  const summary =
    window === 'preflight'
      ? t('charts.summary.baseline', {
          metric: label,
          mean: `${format(corridor.mean)} ${spec.unit}`,
          low: format(corridor.low),
          high: `${format(corridor.high)} ${spec.unit}`,
        })
      : t(SUMMARY_KEY[state], {
          metric: label,
          percent: `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(deviationPercent(mean, corridor))}%`,
        })

  const title = `${label} (${spec.unit})`
  return (
    <ExpandableChart
      title={title}
      renderChart={(expanded, onExpand) => (
        <CorridorChart
          title={title}
          expanded={expanded}
          onExpand={onExpand}
          summary={summary}
          state={state}
          stateLabel={t(STATE_LABEL[state])}
          x={series.x}
          y={series.y}
          corridor={corridor}
          xFormat={xFormat}
          format={format}
          emptyMessage={t('charts.empty')}
        />
      )}
    />
  )
}
