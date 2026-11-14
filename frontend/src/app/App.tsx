import { Suspense, useEffect, useState } from 'react'
import { ChatDrawer } from '@/features/chat'
import { loadConfig } from '@/lib/config'
import { initDataSource } from '@/lib/data'
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
        return setLocale(config.locale)
      })
      .catch((error) => console.warn('startup failed', error))
      .finally(() => setReady(true))
  }, [])

  const mustSelectCrew = !activeCrew && path !== CREW_PATH
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
