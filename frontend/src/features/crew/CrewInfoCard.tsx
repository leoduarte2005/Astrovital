import { useI18n } from '@/lib/i18n'
import type { CrewMember } from '@/lib/model/crew'
import { statureM } from '@/lib/model/stature'
import { Chip } from '@/ui/Chip'
import styles from './CrewInfoCard.module.css'

interface CrewInfoCardProps {
  member: CrewMember
}

/** Floating card with the active crew member's data, so the twin's height can be compared at a glance. */
export function CrewInfoCard({ member }: CrewInfoCardProps) {
  const { t, locale } = useI18n()
  const heightCm = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(statureM(member.nationality) * 100)
  const country = new Intl.DisplayNames([locale], { type: 'region' }).of(member.nationality)

  return (
    <section
      className={styles.root}
      aria-label={t('crew.info.title')}
    >
      <h2 className={styles.name}>{member.fullName}</h2>
      <p className={styles.role}>{t(`enum.crewRole.${member.role}`)}</p>
      <div className={styles.row}>
        <span className={styles.label}>{t('crew.info.height')}</span>
        <span className={styles.value}>
          {heightCm}
          <span className={styles.unit}>cm</span>
        </span>
      </div>
      <div className={styles.row}>
        <span className={styles.label}>{t('crew.info.nationality')}</span>
        <Chip>{country}</Chip>
      </div>
      <p className={styles.note}>{t('crew.info.estimateNote')}</p>
    </section>
  )
}
