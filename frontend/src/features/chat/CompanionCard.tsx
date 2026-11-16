import { useChat } from '@/lib/data/chat'
import { useCrewContext } from '@/lib/data/useCrewContext'
import { useI18n } from '@/lib/i18n'
import styles from './CompanionCard.module.css'

/** Items shown per list: the card stays short. */
const MAX_ITEMS = 3

interface CompanionCardProps {
  /** Called after a suggestion is sent, to take the crew member to where the reply is shown. */
  onAsk: () => void
}

/**
 * The personal companion on the crew member's overview: the greeting from their profile, what helps them recover,
 * and their own suggestions, each sent to the assistant in one touch. Free text from the crew context.
 */
export function CompanionCard({ onAsk }: CompanionCardProps) {
  const { t } = useI18n()
  const context = useCrewContext()
  const send = useChat((state) => state.send)
  const awaiting = useChat((state) => state.pendingId !== null)
  if (!context) return null

  const ask = (text: string) => {
    send(text)
    onAsk()
  }

  return (
    <section className={styles.root} aria-labelledby="companion-title">
      <h2 id="companion-title" className={styles.heading}>
        {t('companion.title')}
      </h2>
      <p className={styles.greeting}>{context.greeting}</p>
      {context.comfort.activities.length > 0 && (
        <>
          <h3 className={styles.label}>{t('companion.helps')}</h3>
          <ul className={styles.helps}>
            {context.comfort.activities.slice(0, MAX_ITEMS).map((activity) => (
              <li key={activity}>{activity}</li>
            ))}
          </ul>
        </>
      )}
      {context.chatSuggestions.length > 0 && (
        <>
          <h3 className={styles.label}>{t('companion.ask')}</h3>
          <ul className={styles.asks}>
            {context.chatSuggestions.slice(0, MAX_ITEMS).map((suggestion) => (
              <li key={suggestion}>
                <button type="button" className={styles.ask} onClick={() => ask(suggestion)} disabled={awaiting}>
                  {suggestion}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
