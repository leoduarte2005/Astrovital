import { useI18n } from '@/lib/i18n'
import { Card } from '@/ui/Card'
import { Icon } from '@/ui/Icon'
import { MODULES } from './modules'
import styles from './ModuleNav.module.css'

export function ModuleNav() {
  const { t } = useI18n()
  return (
    <nav className={styles.root} aria-label={t('nav.label')}>
      {MODULES.map((module) => (
        <Card key={module.path} href={module.path}>
          <Icon name={module.icon} />
          {t(module.labelKey)}
        </Card>
      ))}
    </nav>
  )
}
