import { lazy, type ComponentType } from 'react'
import { MODULES } from '@/features/navigation'
import type { MessageKey } from '@/lib/i18n'
import PlaceholderPage from '@/pages/placeholder'

const placeholder = (titleKey: MessageKey): ComponentType => {
  const Page = () => <PlaceholderPage titleKey={titleKey} />
  return Page
}

/**
 * Route table. Module routes stay placeholders until their screen is built (rules/features-map.md).
 * Routes listed after the spread have their own page and take precedence.
 */
export const routes: Record<string, ComponentType> = {
  '/': lazy(() => import('@/pages/home')),
  '/crew': lazy(() => import('@/pages/crew')),
  ...Object.fromEntries(MODULES.map((module) => [module.path, placeholder(module.labelKey)])),
  '/charts': lazy(() => import('@/pages/charts')),
  '/garden': lazy(() => import('@/pages/garden')),
  '/games': lazy(() => import('@/pages/games')),
  '/leisure': lazy(() => import('@/pages/leisure')),
  // Full-page games: each opens in its own tab, outside the crew session (see App).
  '/game/asteroids': lazy(() => import('@/pages/gameAsteroids')),
  '/game/landing': lazy(() => import('@/pages/gameLanding')),
}
