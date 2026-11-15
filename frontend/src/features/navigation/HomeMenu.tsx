import { useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { navigate } from '@/lib/utils/hashRoute'
import { IconDrawer } from '@/ui/IconDrawer'
import { MODULES } from './modules'

const HOME_ITEMS = MODULES.filter((module) => module.homeMenu)

/** Module shortcuts for the home, behind an icon button. Items come from `MODULES`. */
export function HomeMenu() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)

  return (
    <IconDrawer
      open={open}
      onOpenChange={setOpen}
      icon="menu"
      openLabel={t('home.menu.open')}
      closeLabel={t('home.menu.close')}
      items={HOME_ITEMS.map((module) => ({
        key: module.path,
        icon: module.icon,
        label: t(module.labelKey),
        onSelect: () => {
          setOpen(false)
          navigate(module.path)
        },
      }))}
    />
  )
}
