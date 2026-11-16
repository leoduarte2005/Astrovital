import { lazy, type ComponentType } from 'react'

const MedicalFollowUpPage = lazy(() => import('@/pages/medicalFollowUp'))
// One component per route family: moving between routes of the same family keeps the page (and its 3D scene) mounted.
const AstronautPage = lazy(() => import('@/pages/astronaut'))
const TrainingPage = lazy(() => import('@/pages/training'))

/**
 * Route table: only the routes that have a screen. Any other path, the empty one included, redirects to the start
 * screen `#/crew` (App). Full-page games open in their own tab, outside the crew session.
 */
export const routes: Record<string, ComponentType> = {
  '/crew': lazy(() => import('@/pages/crew')),
  '/astronaut': AstronautPage,
  '/astronaut/training': TrainingPage,
  '/astronaut/medical': MedicalFollowUpPage,
  '/astronaut/personal': AstronautPage,
  '/game/asteroids': lazy(() => import('@/pages/gameAsteroids')),
  '/game/landing': lazy(() => import('@/pages/gameLanding')),
}
