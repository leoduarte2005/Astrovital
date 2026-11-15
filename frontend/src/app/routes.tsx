import { lazy, type ComponentType } from 'react'
import { MODULES } from '@/features/navigation'
import type { MessageKey } from '@/lib/i18n'
import PlaceholderPage from '@/pages/placeholder'

const placeholder = (titleKey: MessageKey): ComponentType => {
  const Page = () => <PlaceholderPage titleKey={titleKey} />
  return Page
}

const MedicalFollowUpPage = lazy(() => import('@/pages/medicalFollowUp'))
// One component per route family: moving between routes of the same family keeps the page (and its 3D scene) mounted.
const AstronautPage = lazy(() => import('@/pages/astronaut'))
const TrainingPage = lazy(() => import('@/pages/training'))

/**
 * Route table. Module routes stay placeholders until their screen is built (rules/features-map.md).
 * Routes listed after the spread have their own page and take precedence.
 */
export const routes: Record<string, ComponentType> = {
  '/': MedicalFollowUpPage,
  '/crew': lazy(() => import('@/pages/crew')),
  '/astronaut': AstronautPage,
  '/astronaut/training': TrainingPage,
  '/astronaut/medical': MedicalFollowUpPage,
  '/astronaut/personal': AstronautPage,
  ...Object.fromEntries(MODULES.map((module) => [module.path, placeholder(module.labelKey)])),
  '/charts': lazy(() => import('@/pages/charts')),
  '/garden': lazy(() => import('@/pages/garden')),
  '/games': lazy(() => import('@/pages/games')),
  '/leisure': lazy(() => import('@/pages/leisure')),
  // Full-page games: each opens in its own tab, outside the crew session (see App).
  '/game/asteroids': lazy(() => import('@/pages/gameAsteroids')),
  '/game/landing': lazy(() => import('@/pages/gameLanding')),
}
