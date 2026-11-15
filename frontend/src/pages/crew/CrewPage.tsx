import { useEffect, useState } from 'react'
import { APP_NAME } from '@/app/constants'
import { CrewStack } from '@/features/crew'
import { StationCanvas } from '@/features/station'
import { getDataSource } from '@/lib/data'
import { rememberCrew } from '@/lib/data/rememberedCrew'
import { sessionStore } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import type { CrewMember } from '@/lib/model/crew'
import { navigate } from '@/lib/utils/hashRoute'
import { CornerPanel } from '@/ui/CornerPanel'
import { GridBackdrop } from '@/ui/GridBackdrop'
import { Hero } from '@/ui/Hero'
import styles from './CrewPage.module.css'

/**
 * Start screen (`#/crew`): the ISS on a grid backdrop, a title block at the top left and the crew stack at the top right.
 * Each card shows its member's heart rate; the links close when the route changes (the unmount).
 */
export default function CrewPage() {
  const { t } = useI18n()
  const [crew, setCrew] = useState<CrewMember[] | null>(null)
  // A section of the ISS is in focus: the title, the crew stack and the grid step aside (the stack stays mounted, so the feeds stay open).
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    // Arriving here always ends the previous session: nothing of the last crew member survives.
    sessionStore.getState().leave()
    let alive = true
    getDataSource()
      .listCrew()
      .then((list) => {
        if (alive) setCrew(list)
      })
      .catch(() => {
        // Central unavailable: the stack stays empty; the ISS still shows.
      })
    return () => {
      alive = false
    }
  }, [])

  const handleSelect = (member: CrewMember) => {
    sessionStore.getState().select(member)
    rememberCrew(member.crewId)
    navigate('/astronaut')
  }

  return (
    <main className={styles.root} data-theme="dark">
      <GridBackdrop grid={!focused}>
        <StationCanvas onFocusChange={setFocused} />
        <CornerPanel corner="top-left" hidden={focused}>
          <Hero title={APP_NAME} tagline={t('crew.hero.tagline')} summary={t('crew.hero.summary')} />
        </CornerPanel>
        {crew && (
          <CornerPanel corner="top-right" hidden={focused}>
            <CrewStack crew={crew} onSelect={handleSelect} />
          </CornerPanel>
        )}
      </GridBackdrop>
    </main>
  )
}
