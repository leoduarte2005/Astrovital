import { useI18n } from '@/lib/i18n'
import type { BaselineTraining } from '@/lib/model/baseline'
import styles from './LongitudinalCharts.module.css'

/** How the baseline was made: period, days with data, and the honest note that it is an estimate, not a diagnosis. */
export function BaselineSummary({ training }: { training: BaselineTraining }) {
  const { t, locale } = useI18n()
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' })
  return (
    <section className={styles.summary} aria-label={t('charts.baseline.title')}>
      <h2 className={styles.summaryTitle}>{t('charts.baseline.title')}</h2>
      <p>{t('charts.baseline.period', { from: date.format(training.trainedFrom), to: date.format(training.trainedTo) })}</p>
      <p>{t('charts.baseline.days', { days: training.days, expected: training.expectedDays })}</p>
      <p>{t('charts.baseline.evidence')}</p>
      <p>{t('charts.baseline.note')}</p>
    </section>
  )
}
