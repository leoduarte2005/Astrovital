import { useI18n, type MessageKey } from '@/lib/i18n'
import { navigate } from '@/lib/utils/hashRoute'
import { Button } from '@/ui/Button'
import styles from './PlaceholderPage.module.css'

/** Stand-in for module screens that are built in later phases. */
export default function PlaceholderPage({ titleKey }: { titleKey: MessageKey }) {
  const { t } = useI18n()
  return (
    <main className={styles.root}>
      <h1 className={styles.title}>{t(titleKey)}</h1>
      <p className={styles.text}>{t('common.comingSoon')}</p>
      <Button icon="back" onClick={() => navigate('/')}>
        {t('common.back')}
      </Button>
    </main>
  )
}
