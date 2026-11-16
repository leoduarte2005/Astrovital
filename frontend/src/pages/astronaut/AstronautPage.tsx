import { useLayoutEffect, useMemo } from 'react'
import { AstronautViewer, sectionOfPath, sectionPath } from '@/features/astronaut'
import { ChatLog, CompanionCard } from '@/features/chat'
import { CrewContextPanel, LearnedTimeline, PrivacyIndicator } from '@/features/crew'
import { GAMES, openGame } from '@/features/games/catalog'
import { PersonalLobby, type PlayableGame } from '@/features/personal'
import { MetricsPanel, vitalFeed } from '@/features/vitals'
import { getDataSource } from '@/lib/data'
import { useSession } from '@/lib/data/session'
import { useCrewContext } from '@/lib/data/useCrewContext'
import { useI18n } from '@/lib/i18n'
import { navigate, useHashRoute } from '@/lib/utils/hashRoute'
import { Icon } from '@/ui/Icon'
import styles from './AstronautPage.module.css'

const CREW_PATH = '/crew'

/**
 * Crew member page, two routes of one family (the model keeps its place in the DOM, so the 3D scene is not reloaded
 * between them). `#/astronaut`: the overview, one contiguous grid: left, who and where in the mission, the health
 * summary, the companion and the privacy statement; centre, the astronaut model with its speech balloon; right,
 * what the assistant learned in the 24 training months. `#/astronaut/personal`: the personal space arranged from the
 * profile on the left (games, books, music, films, activities), the model in the centre and the assistant on the
 * right. The tabs are in the app shell.
 */
export default function AstronautPage() {
  const { t } = useI18n()
  const member = useSession((state) => state.activeCrew)
  const crewId = member?.crewId ?? null
  const section = sectionOfPath(useHashRoute())
  const context = useCrewContext()
  const personal = section === 'personal'
  const overview = section === null
  // The games built on board, for the personal space. Each opens in its own tab, as on `#/games`.
  const games = useMemo<PlayableGame[]>(
    () =>
      GAMES.map((game) => ({
        id: game.id,
        title: t(game.titleKey),
        description: t(game.descriptionKey),
        tags: game.tags,
        onPlay: () => openGame(game.path),
      })),
    [t],
  )

  // Latest readings for the health summary: the same link and crew switch as the medical page, while mounted.
  useLayoutEffect(() => {
    if (!crewId) return
    const source = getDataSource()
    source.open()
    source.setCrew(crewId)
    vitalFeed.start(source)
    return () => {
      vitalFeed.stop()
      source.close()
    }
  }, [crewId])

  // Without a crew member the app redirects to the crew selection (App), so this page always has one.
  if (!member) return null

  return (
    <main className={`${styles.root} ${overview ? styles.overview : ''} ${personal ? styles.personal : ''}`}>
      {personal && (
        <aside className={`${styles.side} ${styles.left}`} aria-label={t('personal.lobby.label')}>
          {context ? <PersonalLobby context={context} games={games} /> : <p className={styles.loading}>{t('common.loading')}</p>}
        </aside>
      )}
      {overview && (
        <aside className={`${styles.side} ${styles.left}`} aria-label={t('overview.left.label')}>
          <nav className={styles.breadcrumb} aria-label={t('overview.breadcrumb.label')}>
            <button type="button" className={styles.crumb} onClick={() => navigate(CREW_PATH)}>
              <Icon name="back" />
              {t('overview.breadcrumb.mission')}
            </button>
            <span aria-hidden="true">/</span>
            <span aria-current="page">{member.fullName}</span>
          </nav>
          <CrewContextPanel member={member} context={context} onSwitch={() => navigate(CREW_PATH)} />
          <div className={styles.health}>
            <MetricsPanel />
          </div>
          <CompanionCard onAsk={() => navigate(sectionPath('medical'))} />
          <div className={styles.fill} />
          <PrivacyIndicator />
        </aside>
      )}
      <div className={styles.stage}>
        <div className={styles.viewer}>
          <AstronautViewer label={t('astronaut.viewer.label', { name: member.fullName })} />
        </div>
        {overview && <p className={styles.balloon}>{t('astronaut.speech.choose')}</p>}
      </div>
      {overview && (
        <aside className={`${styles.side} ${styles.right}`} aria-label={t('learned.title')}>
          {context ? <LearnedTimeline context={context} /> : <p className={styles.loading}>{t('common.loading')}</p>}
        </aside>
      )}
      {personal && (
        <aside className={`${styles.side} ${styles.right} ${styles.assistant}`} aria-label={t('chat.drawer.title')}>
          <h2 className={styles.heading}>{t('chat.log.title')}</h2>
          <ChatLog />
        </aside>
      )}
    </main>
  )
}
