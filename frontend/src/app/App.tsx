import { Suspense, useEffect, useState } from 'react'
import { ChatDrawer } from '@/features/chat'
import { loadConfig } from '@/lib/config'
import { initDataSource } from '@/lib/data'
import { restoreRememberedCrew } from '@/lib/data/rememberedCrew'
import { useSession } from '@/lib/data/session'
import { setLocale, useI18n } from '@/lib/i18n'
import { navigate, useHashRoute } from '@/lib/utils/hashRoute'
import { routes } from './routes'

const CREW_PATH = '/crew'

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
  return (
    <>
      <Suspense fallback={null}>{Page ? <Page /> : <p>{t('common.notFound')}</p>}</Suspense>
      {activeCrew && path !== CREW_PATH && <ChatDrawer />}
    </>
  )
}
