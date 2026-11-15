import { useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { navigate } from '@/lib/utils/hashRoute'
import { IconDrawer, type IconDrawerItem } from '@/ui/IconDrawer'
import { MODULES } from './modules'

const HOME_ITEMS = MODULES.filter((module) => module.homeMenu)

/**
 * The floating menu: home, crew switch, then the module shortcuts (items from `MODULES`). The same menu is on
 * the home header and on the other pages (see App), so these shortcuts are always one click away.
 */
export function HomeMenu() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)

  const go = (path: string) => () => {
    setOpen(false)
    navigate(path)
  }
  const items: IconDrawerItem[] = [
    { key: 'home', icon: 'home', label: t('nav.home'), onSelect: go('/') },
    { key: 'crew', icon: 'swap', label: t('home.switchCrew'), onSelect: go('/crew') },
    ...HOME_ITEMS.map((module) => ({ key: module.path, icon: module.icon, label: t(module.labelKey), onSelect: go(module.path) })),
  ]

  return (
    <IconDrawer
      open={open}
      onOpenChange={setOpen}
      icon="menu"
      openLabel={t('home.menu.open')}
      closeLabel={t('home.menu.close')}
      items={items}
    />
  )
}
