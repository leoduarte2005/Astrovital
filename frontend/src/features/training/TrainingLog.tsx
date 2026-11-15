import { useI18n, type MessageKey } from '@/lib/i18n'
import type { CrewId } from '@/lib/data/mock/crewLore'
import styles from './TrainingLog.module.css'

/** Short name of each crew member in the message keys (`training.log.<name>.m<NN>`). Internal, not shown. */
const SHORT_NAME: Record<CrewId, string> = {
  crew_001: 'silva',
  crew_002: 'costa',
  crew_003: 'sato',
}

interface TrainingLogProps {
  /** 0..23. */
  monthIndex: number
  /** The crew member the camera follows: only his month is written here. */
  crewId: CrewId | null
}

/** What happened to the followed crew member in the chosen month, in the active locale. */
export function TrainingLog({ monthIndex, crewId }: TrainingLogProps) {
  const { t } = useI18n()
  if (!crewId) return null
  const month = String(monthIndex + 1).padStart(2, '0')
  const key = `training.log.${SHORT_NAME[crewId]}.m${month}` as MessageKey
  return (
    <aside className={styles.root} aria-label={t('training.log.title')}>
      <p className={styles.title}>{t('training.log.title')}</p>
      <p className={styles.text}>{t(key)}</p>
    </aside>
  )
}
