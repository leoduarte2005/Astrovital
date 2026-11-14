import { TwinCanvas } from '@/features/twin3d'
import { useSession } from '@/lib/data/session'
import { useI18n } from '@/lib/i18n'
import { navigate } from '@/lib/utils/hashRoute'
import { IconButton } from '@/ui/IconButton'
import styles from './HomePage.module.css'

export default function HomePage() {
  const { t } = useI18n()
  const crew = useSession((state) => state.activeCrew)
  if (!crew) return null

  return (
    <main className={styles.root}>
      <header className={styles.bar}>
        <IconButton icon="swap" label={t('home.switchCrew')} onClick={() => navigate('/crew')} />
      </header>
      <section className={styles.stage}>
        <TwinCanvas skinTone={crew.skinTone} />
      </section>
    </main>
  )
}
