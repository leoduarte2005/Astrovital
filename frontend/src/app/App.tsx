import { AstronautTabs, ASTRONAUT_PATH, sectionPath } from '@/features/astronaut'
import { ChatDrawer } from '@/features/chat'
import { CrewSummary, PrivacyIndicator } from '@/features/crew'
import { loadConfig } from '@/lib/config'
import { initDataSource } from '@/lib/data'
import { restoreRememberedCrew } from '@/lib/data/rememberedCrew'
import { useSession } from '@/lib/data/session'
import { setLocale, useI18n } from '@/lib/i18n'
import { CORNER_SLOT_ID } from '@/lib/utils/cornerSlot'
import { navigate, useHashRoute } from '@/lib/utils/hashRoute'
import { IconButton } from '@/ui/IconButton'
import { Suspense, useEffect, useState } from 'react'
import styles from './App.module.css'
import { routes } from './routes'

/** The start screen, and the default route: empty and unknown paths go here. */
const CREW_PATH = '/crew'

export function App() {
  const [ready, setReady] = useState(false)
  const path = useHashRoute()
  const activeCrew = useSession((state) => state.activeCrew)
  const { t } = useI18n()
  const Page = routes[path]
  // Game tabs run without a crew member: they are opened in a new tab, where the session is empty.
  const isGame = path.startsWith('/game/')

  useEffect(() => {
    loadConfig()
      .then((config) => {
        initDataSource(config.source)
        // Reloads go back to the remembered member, unless the page is the start screen (an empty hash is that screen).
        const hashPath = window.location.hash.replace(/^#/, '') || CREW_PATH
        const onCrewPage = hashPath === CREW_PATH
        return setLocale(config.locale).then(() => (onCrewPage ? undefined : restoreRememberedCrew()))
      })
      .catch((error) => console.warn('startup failed', error))
      .finally(() => setReady(true))
  }, [])

  // Unknown and empty routes go to the default route, the start screen.
  useEffect(() => {
    if (ready && !Page) navigate(CREW_PATH)
  }, [ready, Page])

  const mustSelectCrew = !activeCrew && path !== CREW_PATH && !isGame
  useEffect(() => {
    if (ready && mustSelectCrew) navigate(CREW_PATH)
  }, [ready, mustSelectCrew])

  if (!ready || !Page || mustSelectCrew) return null

  // The section tabs: on every page but the start screen and the game tabs (full-page games, no crew member).
  const showTabs = path !== CREW_PATH && !isGame
  // The medical follow-up and the personal space show the assistant inline, in their right column: no drawer there,
  // and no corner card either.
  const chatInline = path === sectionPath('medical') || path === sectionPath('personal')
  // The overview shows the crew member and the privacy statement in its left column: no corner card either.
  const showCorner = showTabs && !chatInline && path !== ASTRONAUT_PATH
  return (
    <>
      <Suspense fallback={null}>
        <Page />
      </Suspense>
      {showTabs && <AstronautTabs />}
      {showCorner && (
        <div className={styles.corner}>
          {activeCrew && (
            <div className={styles.crewSummaryRow}>
              <CrewSummary member={activeCrew} />
              <IconButton icon="swap" label={t('home.switchCrew')} onClick={() => navigate(CREW_PATH)} />
            </div>
          )}
          <PrivacyIndicator variant="compact" />
          <div id={CORNER_SLOT_ID} />
        </div>
      )}
      {activeCrew && path !== CREW_PATH && !chatInline && <ChatDrawer />}
    </>
  )
}
