import { useMemo } from 'react'
import { useI18n } from '@/lib/i18n'
import type { CrewContext } from '@/lib/model/crewContext'
import styles from './LearnedTimeline.module.css'

const TRAINING_MONTHS = 24

/**
 * "What Astro Vital learned": the 24 training months, newest first, each with its programme phase, title, the
 * notes the assistant kept and the wellbeing the crew member reported. Reported data, not a diagnosis. Free text
 * comes from the crew record and is not translated (rules/i18n.md).
 */
export function LearnedTimeline({ context }: { context: CrewContext }) {
  const { t, locale } = useI18n()
  const formats = useMemo(
    () => ({
      period: new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric', timeZone: 'UTC' }),
      hours: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
    }),
    [locale],
  )
  const wellbeing = new Map(context.wellbeing.map((entry) => [entry.month, entry]))
  const newestFirst = [...context.learned].reverse()

  return (
    <section className={styles.root} aria-labelledby="learned-title">
      <header className={styles.header}>
        <h2 id="learned-title" className={styles.heading}>
          {t('learned.title')}
        </h2>
        <p className={styles.status}>{t('learned.status')}</p>
      </header>
      <ol className={styles.list}>
        {newestFirst.map((month) => {
          const mood = wellbeing.get(month.month)
          return (
            <li key={month.month} className={styles.month}>
              <p className={styles.meta}>
                {t('learned.month', { month: month.month, total: TRAINING_MONTHS })} ·{' '}
                {formats.period.format(new Date(`${month.period}-01T00:00:00Z`))} · {month.phase}
              </p>
              <h3 className={styles.title}>{month.title}</h3>
              <ul className={styles.notes}>
                {month.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
              {mood && (
                <p className={styles.wellbeing}>
                  {t('learned.wellbeing', { mood: mood.mood, sleep: formats.hours.format(mood.sleepH), stress: mood.stress })}
                </p>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
