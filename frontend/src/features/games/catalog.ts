import type { MessageKey } from '@/lib/i18n'

export interface GameEntry {
  id: string
  /** Route of the game's own page. It opens in a new browser tab. */
  path: string
  titleKey: MessageKey
  descriptionKey: MessageKey
  /**
   * Word starts that describe the game, compared with the game genres of the crew profile (in English, lower case),
   * so the personal space can say which taste a game matches.
   */
  tags: string[]
}

export const GAMES: GameEntry[] = [
  {
    id: 'landing',
    path: '/game/landing',
    titleKey: 'games.landing.title',
    descriptionKey: 'games.landing.description',
    tags: ['simulat', 'flight', 'precision', 'platform'],
  },
  {
    id: 'asteroids',
    path: '/game/asteroids',
    titleKey: 'games.asteroids.title',
    descriptionKey: 'games.asteroids.description',
    tags: ['explor', 'arcade', 'spacecraft'],
  },
]

/** Opens a game in a new tab, on the same app and origin. The new tab does not need the crew session. */
export function openGame(path: string): void {
  window.open(`${window.location.pathname}${window.location.search}#${path}`, '_blank', 'noopener')
}
