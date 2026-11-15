import { APP_NAME } from '@/app/constants'
import { LongitudinalCharts } from '@/features/longitudinal'
import { useI18n } from '@/lib/i18n'
import styles from './ChartsPage.module.css'

/** Longitudinal charts of the active crew member against their own baseline (rules/charts.md). */
export default function ChartsPage() {
  const { t } = useI18n()
  return (
    <main className={styles.root}>
      <header className={styles.header}>
        <p className={styles.brand}>{APP_NAME}</p>
        <h1 className={styles.title}>{t('charts.title')}</h1>
        <p className={styles.subtitle}>{t('charts.subtitle')}</p>
      </header>
      <LongitudinalCharts />
    </main>
  )
}
