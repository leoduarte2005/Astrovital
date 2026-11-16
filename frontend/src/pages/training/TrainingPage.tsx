import { TrainingAbout, TrainingScene } from '@/features/training'
import { useSession } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import styles from './TrainingPage.module.css'

/**
 * Training section (`#/astronaut/training`): the training hangar full screen, with the crew avatars and the timeline
 * of the 24 months before the mission. The section tabs are in the app shell, fixed above it. The card at the bottom
 * left explains what the page is and how its controls and monthly notes work.
 */
export default function TrainingPage() {
  const { t } = useI18n()
  const member = useSession((state) => state.activeCrew)

  // Without a crew member the app redirects to the crew selection (App), so this page always has one.
  if (!member) return null

  return (
    <main className={styles.root}>
      <TrainingScene label={t('training.hangar.label')} />
      <TrainingAbout />
    </main>
  )
}
