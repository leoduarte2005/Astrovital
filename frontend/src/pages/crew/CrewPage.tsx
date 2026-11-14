import { useEffect, useState } from 'react'
import { APP_NAME } from '@/app/constants'
import { CrewCard } from '@/features/crew'
import { getDataSource } from '@/lib/data'
import { sessionStore } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import type { CrewMember } from '@/lib/model/crew'
import { navigate } from '@/lib/utils/hashRoute'
import styles from './CrewPage.module.css'

export default function CrewPage() {
  const { t } = useI18n()
  const [crew, setCrew] = useState<CrewMember[] | null>(null)

  useEffect(() => {
    // Arriving here always ends the previous session: nothing of the last crew member survives.
    sessionStore.getState().leave()
    getDataSource().listCrew().then(setCrew)
  }, [])

  const handleSelect = (member: CrewMember) => {
    sessionStore.getState().select(member)
    navigate('/')
  }

  return (
    <main className={styles.root}>
      <header className={styles.header}>
        <p className={styles.brand}>{APP_NAME}</p>
        <h1 className={styles.title}>{t('crew.select.title')}</h1>
        <p className={styles.subtitle}>{t('crew.select.subtitle')}</p>
      </header>
      {crew ? (
        <div className={styles.grid}>
          {crew.map((member) => (
            <CrewCard key={member.crewId} member={member} onSelect={handleSelect} />
          ))}
        </div>
      ) : (
        <p className={styles.subtitle}>{t('common.loading')}</p>
      )}
    </main>
  )
}
