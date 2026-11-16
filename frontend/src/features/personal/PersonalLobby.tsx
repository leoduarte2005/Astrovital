import { useEffect, useState, type ReactNode } from 'react'
import { getDataSource } from '@/lib/data'
import { useChat } from '@/lib/data/chat'
import { bookFileUrl, type Book } from '@/lib/data/mock/bookCatalog'
import { useI18n, type MessageKey } from '@/lib/i18n'
import type { CrewContext } from '@/lib/model/crewContext'
import { Button } from '@/ui/Button'
import { Icon, type IconName } from '@/ui/Icon'
import styles from './PersonalLobby.module.css'

/** A game that is built and runs on board. The page passes them in: features do not import each other. */
export interface PlayableGame {
  id: string
  title: string
  description: string
  /** Word starts compared with the profile's game genres (see `features/games/catalog.ts`). */
  tags: string[]
  onPlay: () => void
}

interface PersonalLobbyProps {
  context: CrewContext
  games: PlayableGame[]
}

type Category = 'games' | 'books' | 'music' | 'films' | 'activities'

const CATEGORIES: { id: Category; icon: IconName; labelKey: MessageKey }[] = [
  { id: 'games', icon: 'gamepad', labelKey: 'personal.section.games' },
  { id: 'books', icon: 'book', labelKey: 'personal.section.books' },
  { id: 'music', icon: 'music', labelKey: 'personal.section.music' },
  { id: 'films', icon: 'film', labelKey: 'personal.section.films' },
  { id: 'activities', icon: 'rocket', labelKey: 'personal.section.activities' },
]

/** Lower case without accents, for comparing tags with the profile's genres. */
function plain(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
}

/** The first profile genre with a word that starts with one of the tags, or null. */
function matchingGenre(tags: string[], genres: string[]): string | null {
  return genres.find((genre) => plain(genre).split(/[^a-z0-9]+/).some((word) => tags.some((tag) => word.startsWith(tag)))) ?? null
}

/** Something on board that can be used now: a small card with its action at the bottom. */
function AvailableCard({ icon, title, detail, meta, action }: { icon: IconName; title: string; detail?: string; meta: string; action: ReactNode }) {
  return (
    <li className={styles.card}>
      <p className={styles.meta}>
        <Icon name={icon} />
        {meta}
      </p>
      <h4 className={styles.name}>{title}</h4>
      {detail && <p className={styles.detail}>{detail}</p>}
      <div className={styles.action}>{action}</div>
    </li>
  )
}

/** Picked by the assistant from the profile, but not on board yet: shown to show the personalisation, not usable. */
function SuggestedCard({ title }: { title: string }) {
  const { t } = useI18n()
  return (
    <li className={`${styles.card} ${styles.suggested}`} aria-disabled="true">
      <p className={styles.meta}>
        <Icon name="lock" />
        {t('personal.status.suggested')}
      </p>
      <h4 className={styles.name}>{title}</h4>
    </li>
  )
}

/**
 * Left column of the personal space: games, books, music, films and on-board activities arranged by the assistant
 * from the crew member's profile (`CrewContext.tastes`, `comfort`). A row of category tabs shows one category at a time
 * as a grid of small cards. What exists on board is usable (the two built games, the books of the on-board library);
 * the rest of the profile shows as suggestions not on board yet. Titles and genres are free text from the profile and
 * are not translated (rules/i18n.md).
 */
export function PersonalLobby({ context, games }: PersonalLobbyProps) {
  const { t } = useI18n()
  const send = useChat((state) => state.send)
  const awaiting = useChat((state) => state.pendingId !== null)
  const [category, setCategory] = useState<Category>('games')
  const [books, setBooks] = useState<{ crewId: string; list: Book[] } | null>(null)
  const { tastes } = context

  useEffect(() => {
    let active = true
    getDataSource()
      .listBookSuggestions(context.crewId)
      .then((list) => {
        if (active) setBooks({ crewId: context.crewId, list })
      })
      .catch((error: unknown) => console.warn('book suggestions unavailable', error))
    return () => {
      active = false
    }
  }, [context.crewId])

  // Games that match a taste of the profile come first, with the taste they match.
  const playable = games
    .map((game) => ({ game, genre: matchingGenre(game.tags, tastes.gameGenres) }))
    .sort((a, b) => Number(b.genre !== null) - Number(a.genre !== null))
  const library = books && books.crewId === context.crewId ? books.list : []
  const activities = context.comfort.activities

  // Per category: what can be used now, what is only suggested, and the genres the assistant considered.
  const onBoard: Record<Category, number> = {
    games: playable.length,
    books: library.length,
    music: 0,
    films: 0,
    activities: activities.length,
  }
  const suggested: Record<Category, number> = {
    games: tastes.games.length,
    books: tastes.books.length,
    music: tastes.music.length,
    films: tastes.films.length,
    activities: 0,
  }
  const genresOf: Record<Category, string[]> = {
    games: tastes.gameGenres,
    books: tastes.bookGenres,
    music: tastes.musicGenres,
    films: tastes.filmGenres,
    activities: [],
  }
  const genres = genresOf[category]

  const suggestions = (list: string[]) => list.map((title) => <SuggestedCard key={title} title={title} />)

  const cards: Record<Category, ReactNode> = {
    games: (
      <>
        {playable.map(({ game, genre }) => (
          <AvailableCard
            key={game.id}
            icon="gamepad"
            title={game.title}
            detail={game.description}
            meta={genre ? t('personal.match', { genre }) : t('personal.status.available')}
            action={
              <Button icon="gamepad" onClick={game.onPlay}>
                {t('personal.play')}
              </Button>
            }
          />
        ))}
        {suggestions(tastes.games)}
      </>
    ),
    books: (
      <>
        {library.map((book) => (
          <AvailableCard
            key={book.id}
            icon="book"
            title={book.title}
            detail={`${book.author} · ${t(`genre.${book.genre}` as MessageKey)}`}
            meta={t('personal.status.available')}
            action={
              <a className={styles.download} href={bookFileUrl(book)} download>
                <Icon name="download" />
                {t('personal.download')}
              </a>
            }
          />
        ))}
        {suggestions(tastes.books)}
      </>
    ),
    music: <>{suggestions(tastes.music)}</>,
    films: <>{suggestions(tastes.films)}</>,
    activities: (
      <>
        {activities.map((activity) => (
          <AvailableCard
            key={activity}
            icon="rocket"
            title={activity}
            meta={t('personal.status.available')}
            action={
              <button type="button" className={styles.ask} onClick={() => send(t('personal.activity.ask', { activity }))} disabled={awaiting}>
                {t('personal.activity.button')}
              </button>
            }
          />
        ))}
      </>
    ),
  }

  return (
    <div className={styles.root}>
      <header className={styles.header}>
        <h2 className={styles.heading}>{t('personal.lobby.title')}</h2>
        <p className={styles.note}>{t('personal.lobby.subtitle')}</p>
        {tastes.hobbies.length > 0 && (
          <ul className={styles.chips} aria-label={t('personal.interests')}>
            {tastes.hobbies.map((hobby) => (
              <li key={hobby} className={styles.chip}>
                {hobby}
              </li>
            ))}
          </ul>
        )}
      </header>

      <div className={styles.tabs} role="tablist" aria-label={t('personal.tabs.label')}>
        {CATEGORIES.map(({ id, icon, labelKey }) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`personal-tab-${id}`}
            aria-selected={id === category}
            aria-controls="personal-panel"
            className={styles.tab}
            title={t(labelKey)}
            aria-label={t(labelKey)}
            onClick={() => setCategory(id)}
          >
            <Icon name={icon} />
          </button>
        ))}
      </div>

      <section id="personal-panel" role="tabpanel" aria-labelledby={`personal-tab-${category}`} className={styles.panel}>
        <header className={styles.panelHead}>
          <h3 className={styles.sectionTitle}>{t(CATEGORIES.find((entry) => entry.id === category)?.labelKey ?? 'personal.section.games')}</h3>
          <p className={styles.note}>{t('personal.count', { onBoard: onBoard[category], suggested: suggested[category] })}</p>
          {genres.length > 0 && <p className={styles.note}>{t('personal.considers', { genres: genres.join(' · ') })}</p>}
        </header>
        <ul className={styles.grid}>{cards[category]}</ul>
      </section>

    </div>
  )
}
