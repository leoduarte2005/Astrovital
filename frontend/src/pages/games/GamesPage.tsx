import { APP_NAME } from '@/app/constants'
import { GAMES, openGame } from '@/features/games/catalog'
import { useI18n } from '@/lib/i18n'
import { Card } from '@/ui/Card'
import styles from './GamesPage.module.css'

/** Game cards. Each one opens its game in a new browser tab. */
export default function GamesPage() {
  const { t } = useI18n()
  return (
    <main className={styles.root}>
      <header className={styles.header}>
        <p className={styles.brand}>{APP_NAME}</p>
        <h1 className={styles.title}>{t('games.title')}</h1>
        <p className={styles.subtitle}>{t('games.subtitle')}</p>
      </header>
      <div className={styles.grid}>
        {GAMES.map((game) => (
          <Card key={game.id} onClick={() => openGame(game.path)} label={t(game.titleKey)}>
            <h2 className={styles.name}>{t(game.titleKey)}</h2>
            <p className={styles.text}>{t(game.descriptionKey)}</p>
          </Card>
        ))}
      </div>
    </main>
  )
}
