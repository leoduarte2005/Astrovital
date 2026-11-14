import type { MessageKey } from '@/lib/i18n'
import type { IconName } from '@/ui/Icon'

export interface AppModule {
  path: string
  icon: IconName
  labelKey: MessageKey
}

/** Module screens reachable from the home. One entry per route in rules/features-map.md. */
export const MODULES: AppModule[] = [
  { path: '/charts', icon: 'chart', labelKey: 'nav.charts' },
  { path: '/diagnosis', icon: 'diagnosis', labelKey: 'nav.diagnosis' },
  { path: '/encyclopedia', icon: 'book', labelKey: 'nav.encyclopedia' },
  { path: '/garden', icon: 'leaf', labelKey: 'nav.garden' },
  { path: '/landing', icon: 'rocket', labelKey: 'nav.landing' },
  { path: '/profile', icon: 'user', labelKey: 'nav.profile' },
]
