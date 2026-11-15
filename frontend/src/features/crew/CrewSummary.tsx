import { useI18n } from '@/lib/i18n'
import type { CrewMember } from '@/lib/model/crew'
import styles from './CrewSummary.module.css'

interface CrewSummaryProps {
  member: CrewMember
}

/** The active crew member at a glance, fixed top left on every page the tabs show: name, country and role. */
export function CrewSummary({ member }: CrewSummaryProps) {
  const { t, locale } = useI18n()
  const country = new Intl.DisplayNames([locale], { type: 'region' }).of(member.nationality)
  return (
    <section className={styles.root} aria-label={t('crew.summary.label')}>
      <h2 className={styles.name}>{member.fullName}</h2>
      <p className={styles.line}>{country}</p>
      <p className={styles.line}>{t(`enum.crewRole.${member.role}`)}</p>
    </section>
  )
}
