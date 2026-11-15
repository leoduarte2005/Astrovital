import type { MessageKey } from '@/lib/i18n'
import type { IconName } from '@/ui/Icon'

export interface AppModule {
  path: string
  icon: IconName
  labelKey: MessageKey
  /** Shown in the home's icon drawer. */
  homeMenu?: boolean
}

/** Module screens. One entry per route in rules/features-map.md. */
export const MODULES: AppModule[] = [
  { path: '/charts', icon: 'chart', labelKey: 'nav.charts', homeMenu: true },
  { path: '/diagnosis', icon: 'diagnosis', labelKey: 'nav.diagnosis' },
  { path: '/encyclopedia', icon: 'book', labelKey: 'nav.encyclopedia', homeMenu: true },
  { path: '/garden', icon: 'leaf', labelKey: 'nav.garden', homeMenu: true },
  { path: '/games', icon: 'rocket', labelKey: 'nav.games', homeMenu: true },
  { path: '/leisure', icon: 'gamepad', labelKey: 'nav.leisure', homeMenu: true },
  { path: '/profile', icon: 'user', labelKey: 'nav.profile' },
]
