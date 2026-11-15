import { AstronautViewer, sectionOfPath } from '@/features/astronaut'
import { useSession } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import { useHashRoute } from '@/lib/utils/hashRoute'
import styles from './AstronautPage.module.css'

/**
 * Crew member page (`#/astronaut`, and the training and personal routes): the astronaut model at the centre of the
 * screen (half the height) on a grid floor, with a speech balloon while no section is chosen. The tabs are in the app shell.
 */
export default function AstronautPage() {
  const { t } = useI18n()
  const member = useSession((state) => state.activeCrew)
  const section = sectionOfPath(useHashRoute())

  // Without a crew member the app redirects to the crew selection (App), so this page always has one.
  if (!member) return null

  return (
    <main className={styles.root}>
      <div className={styles.viewer}>
        <AstronautViewer label={t('astronaut.viewer.label', { name: member.fullName })} />
      </div>
      {section === null && <p className={styles.balloon}>{t('astronaut.speech.choose')}</p>}
    </main>
  )
}
