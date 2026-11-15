import { useI18n } from '@/lib/i18n'
import { navigate, useHashRoute } from '@/lib/utils/hashRoute'
import { SegmentedControl } from '@/ui/SegmentedControl'
import { ASTRONAUT_SECTIONS, sectionOfPath, sectionPath } from './sections'
import styles from './AstronautTabs.module.css'

/**
 * The three sections of the crew member, as tabs fixed at the top centre. The chosen tab is the route
 * (`#/astronaut/<section>`); choosing one navigates to it. The app shell shows it on every page but the crew selection.
 */
export function AstronautTabs() {
  const { t } = useI18n()
  const section = sectionOfPath(useHashRoute())
  return (
    <div className={styles.root}>
      <div className={styles.tabs}>
        <SegmentedControl
          label={t('astronaut.tabs.label')}
          value={section}
          onChange={(id) => navigate(sectionPath(id))}
          options={ASTRONAUT_SECTIONS.map((id) => ({ value: id, label: t(`astronaut.tabs.${id}`) }))}
        />
      </div>
    </div>
  )
}
