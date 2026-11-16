import { useI18n } from '@/lib/i18n'
import styles from './TrainingAbout.module.css'

/**
 * Bottom-left card of the training page: what the page is (a simulator of what the AI learned during the 24 months
 * of training before the mission to the ISS), and how the time controls and the monthly notes work. Static text.
 */
export function TrainingAbout() {
  const { t } = useI18n()
  return (
    <aside className={styles.root} aria-label={t('training.about.label')}>
      <header className={styles.header}>
        <h2 className={styles.title}>{t('training.about.title')}</h2>
        <span className={styles.badge}>{t('training.about.badge')}</span>
      </header>
      <p className={styles.lead}>{t('training.about.what')}</p>
      <dl className={styles.items}>
        <dt className={styles.term}>{t('training.about.controlsTitle')}</dt>
        <dd className={styles.definition}>{t('training.about.controls')}</dd>
        <dt className={styles.term}>{t('training.about.notesTitle')}</dt>
        <dd className={styles.definition}>{t('training.about.notes')}</dd>
      </dl>
    </aside>
  )
}
