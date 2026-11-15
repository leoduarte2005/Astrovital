import { formatList, useI18n } from '@/lib/i18n'
import type { CrewMember } from '@/lib/model/crew'
import { Card } from '@/ui/Card'
import { Chip } from '@/ui/Chip'
import { CrewFigure } from './CrewFigure'
import styles from './CrewCard.module.css'

interface CrewCardProps {
  member: CrewMember
  onSelect: (member: CrewMember) => void
}

export function CrewCard({ member, onSelect }: CrewCardProps) {
  const { t, locale } = useI18n()
  const missionDay = member.missionDay === null ? null : new Intl.NumberFormat(locale).format(member.missionDay)
  const shares =
    member.shares.length > 0
      ? t('crew.privacy.shares', { items: formatList(member.shares.map((scope) => t(`enum.shareScope.${scope}`))) })
      : t('crew.privacy.none')

  return (
    <Card onClick={() => onSelect(member)} label={t('crew.card.select', { name: member.fullName })}>
      <div className={styles.figure}>
        <CrewFigure accent={member.accent} />
      </div>
      <h2 className={styles.name}>{member.fullName}</h2>
      <p className={styles.role}>{t(`enum.crewRole.${member.role}`)}</p>
      {missionDay !== null && <p className={styles.meta}>{t('crew.card.missionDay', { day: missionDay })}</p>}
      {member.calibrationRequired && <Chip icon="signal">{t('crew.card.calibration')}</Chip>}
      <Chip icon="lock" dot={member.accent}>
        {shares}
      </Chip>
    </Card>
  )
}
