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
  const { t } = useI18n()
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
      <Chip icon="lock" dot={member.accent}>
        {shares}
      </Chip>
    </Card>
  )
}
