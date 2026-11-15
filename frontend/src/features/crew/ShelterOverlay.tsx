import { useI18n } from '@/lib/i18n'
import { Icon } from '@/ui/Icon'
import styles from './ShelterOverlay.module.css'

/** Full-screen alert while the central reports `MODE_RADIATION_ALERT`. Icon and text, never colour alone. */
export function ShelterOverlay() {
  const { t } = useI18n()
  return (
    <div className={styles.root} role="alertdialog" aria-modal="true" aria-labelledby="shelter-title">
      <div className={styles.panel}>
        <span className={styles.icon}>
          <Icon name="alert" />
        </span>
        <h2 id="shelter-title" className={styles.title}>
          {t('home.shelter.title')}
        </h2>
        <p className={styles.text}>{t('home.shelter.body')}</p>
      </div>
    </div>
  )
}
