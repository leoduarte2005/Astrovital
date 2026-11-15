import { AstronautTabs } from '@/features/astronaut'
import { CrewSummary } from '@/features/crew'
import { ChatDrawer } from '@/features/chat'
import { HomeMenu } from '@/features/navigation'
import { loadConfig } from '@/lib/config'
import { initDataSource } from '@/lib/data'
import { restoreRememberedCrew } from '@/lib/data/rememberedCrew'
import { useSession } from '@/lib/data/session'
import { setLocale, useI18n } from '@/lib/i18n'
import { CORNER_SLOT_ID } from '@/lib/utils/cornerSlot'
import { navigate, useHashRoute } from '@/lib/utils/hashRoute'
import { Suspense, useEffect, useState } from 'react'
import styles from './App.module.css'
import { routes } from './routes'

const CREW_PATH = '/crew'

// Off for now: the floating drawer is not rendered on any page (rules/features-map.md). Set to true to bring it back.
const SHOW_HOME_MENU = false

export function App() {
  const [ready, setReady] = useState(false)
  const path = useHashRoute()
  const activeCrew = useSession((state) => state.activeCrew)
  const { t } = useI18n()

  useEffect(() => {
    loadConfig()
      .then((config) => {
        initDataSource(config.source)
        // Reloads go back to the remembered member, unless the page is the crew selection itself.
        const onCrewPage = window.location.hash.replace(/^#/, '') === CREW_PATH
        return setLocale(config.locale).then(() => (onCrewPage ? undefined : restoreRememberedCrew()))
      })
      .catch((error) => console.warn('startup failed', error))
      .finally(() => setReady(true))
  }, [])

  // Game tabs run without a crew member: they are opened in a new tab, where the session is empty.
  const mustSelectCrew = !activeCrew && path !== CREW_PATH && !path.startsWith('/game/')
  useEffect(() => {
    if (ready && mustSelectCrew) navigate(CREW_PATH)
  }, [ready, mustSelectCrew])

  if (!ready || mustSelectCrew) return null

  const Page = routes[path]
  // Same fixed place on every page, like the chat sidebar. Hidden on the crew selection and in game tabs (full-page games).
  const showMenu = SHOW_HOME_MENU && path !== CREW_PATH && !path.startsWith('/game/')
  // The section tabs: on every page but the crew selection and the game tabs (full-page games, no crew member).
  const showTabs = path !== CREW_PATH && !path.startsWith('/game/')
  return (
    <>
      <Suspense fallback={null}>{Page ? <Page /> : <p>{t('common.notFound')}</p>}</Suspense>
      {showTabs && <AstronautTabs />}
      {showTabs && (
        <div className={styles.corner}>
          {activeCrew && <CrewSummary member={activeCrew} />}
          <div id={CORNER_SLOT_ID} />
        </div>
      )}
      {showMenu && (
        <div className={styles.menu}>
          <HomeMenu />
        </div>
      )}
      {activeCrew && path !== CREW_PATH && <ChatDrawer />}
    </>
  )
}
