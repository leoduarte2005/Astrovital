import { useI18n, type MessageKey } from '@/lib/i18n'
import { STATION_PRIVACY } from '@/lib/model/crewContext'
import { Icon, type IconName } from '@/ui/Icon'
import styles from './PrivacyIndicator.module.css'

const LINES: { icon: IconName; key: MessageKey }[] = [
  { icon: 'signal', key: `privacy.sensing.${STATION_PRIVACY.sensing}` },
  { icon: 'lock', key: `privacy.camera.${STATION_PRIVACY.camera}` },
  { icon: 'lock', key: `privacy.network.${STATION_PRIVACY.network}` },
  { icon: 'user', key: `privacy.isolation.${STATION_PRIVACY.isolation}` },
]

interface PrivacyIndicatorProps {
  /** `panel`: a titled cell of a side column. `compact`: one short line, for the fixed corner of the other pages. */
  variant?: 'panel' | 'compact'
}

/**
 * Always-visible statement of how the cabin is sensed and where the data stays (static, the same for every crew
 * member): a panel in the side columns of the overview and the medical page, a compact line everywhere else.
 */
export function PrivacyIndicator({ variant = 'panel' }: PrivacyIndicatorProps) {
  const { t } = useI18n()
  if (variant === 'compact') {
    return (
      <p className={styles.compact} aria-label={t('privacy.title')}>
        <Icon name="signal" />
        <span>{LINES.map(({ key }) => t(key)).join(' · ')}</span>
      </p>
    )
  }
  return (
    <section className={styles.root} aria-labelledby="privacy-title">
      <h2 id="privacy-title" className={styles.heading}>
        {t('privacy.title')}
      </h2>
      <ul className={styles.list}>
        {LINES.map(({ icon, key }) => (
          <li key={key} className={styles.line}>
            <Icon name={icon} />
            <span>{t(key)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
