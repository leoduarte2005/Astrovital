import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { getDataSource } from '@/lib/data'
import { useChat, type ChatMessage } from '@/lib/data/chat'
import { useCrewContext } from '@/lib/data/useCrewContext'
import { useI18n } from '@/lib/i18n'
import { Icon } from '@/ui/Icon'
import { IconButton } from '@/ui/IconButton'
import styles from './ChatLog.module.css'

/** Suggestions offered while the log is empty. */
const MAX_SUGGESTIONS = 4

function Entry({ message, time }: { message: ChatMessage; time: Intl.DateTimeFormat }) {
  const { t } = useI18n()
  const reply = message.reply
  return (
    <article className={styles.entry} data-role={message.role}>
      <header className={styles.head}>
        <time dateTime={new Date(message.at).toISOString()}>{time.format(message.at)}</time>
        <span className={styles.who}>{message.role === 'user' ? t('chat.log.crew') : t('chat.log.assistant')}</span>
        {reply && <span className={styles.escalation}>{t(`chat.escalation.${reply.escalation}`)}</span>}
      </header>
      {/* Text from the crew member or the AI: never translated (rules/i18n.md). */}
      <p className={styles.text}>{message.text}</p>
      {reply && reply.evidence.length > 0 && (
        <section className={styles.evidence} aria-label={t('chat.evidence.title')}>
          <h3 className={styles.label}>{t('chat.evidence.title')}</h3>
          <ul className={styles.rows}>
            {reply.evidence.map((item) => (
              <li key={item} className={styles.evidenceRow}>
                <Icon name="signal" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {reply && reply.countermeasures.length > 0 && (
        <section className={styles.block} aria-label={t('chat.steps.title')}>
          <h3 className={styles.label}>{t('chat.steps.title')}</h3>
          <ol className={styles.steps}>
            {reply.countermeasures.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </section>
      )}
      {reply && (
        <footer className={styles.foot}>
          {reply.sources.length > 0 && (
            <p>
              <span className={styles.label}>{t('chat.source')}</span> {reply.sources.join(' · ')}
            </p>
          )}
          <p>{reply.disclaimer}</p>
        </footer>
      )}
    </article>
  )
}

/**
 * The assistant as a clinical log: report entries with time, role and the reply's evidence, steps and source,
 * instead of chat bubbles. Used inline on the medical page and inside the chat drawer elsewhere. Holds its own
 * reference on the live link, so replies arrive wherever it is shown.
 */
export function ChatLog() {
  const { t, locale } = useI18n()
  const context = useCrewContext()
  const [draft, setDraft] = useState('')
  const messages = useChat((state) => state.messages)
  const send = useChat((state) => state.send)
  const awaiting = useChat((state) => state.pendingId !== null)
  const lastRole = useChat((state) => state.messages.at(-1)?.role ?? null)
  const inputRef = useRef<HTMLInputElement>(null)
  const previous = useRef({ awaiting, lastRole })
  const time = useMemo(() => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }), [locale])

  useEffect(() => {
    const source = getDataSource()
    source.open()
    return () => source.close()
  }, [])

  // Focus the input when the assistant has answered and the input is enabled again. The reply lands before the
  // pending flag clears, so the focus waits for the second change. Mounting with an old reply does not steal it.
  useEffect(() => {
    const answered =
      (previous.current.awaiting && !awaiting) || (lastRole === 'assistant' && previous.current.lastRole !== 'assistant')
    previous.current = { awaiting, lastRole }
    if (answered && !awaiting) inputRef.current?.focus()
  }, [awaiting, lastRole])

  const submit = (text = draft) => {
    if (!text.trim() || awaiting) return
    send(text)
    setDraft('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') submit()
  }

  // DOM order is newest first: with column-reverse the newest entry sits at the bottom.
  const newestFirst = [...messages].reverse()
  const suggestions = context?.chatSuggestions.slice(0, MAX_SUGGESTIONS) ?? []

  return (
    <div className={styles.chat}>
      <div className={styles.messages} role="log" aria-live="polite" aria-label={t('chat.drawer.title')}>
        {awaiting && <p className={styles.pending}>{t('chat.log.pending')}</p>}
        {newestFirst.map((message) => (
          <Entry key={message.id} message={message} time={time} />
        ))}
        {messages.length === 0 && (
          <div className={styles.empty}>
            <p>{t('chat.drawer.empty')}</p>
            {suggestions.length > 0 && (
              <section aria-label={t('chat.suggestions.title')}>
                <h3 className={styles.label}>{t('chat.suggestions.title')}</h3>
                {/* Suggestions come from the crew context: free text, not translated. */}
                <ul className={styles.suggestions}>
                  {suggestions.map((suggestion) => (
                    <li key={suggestion}>
                      <button type="button" className={styles.suggestion} onClick={() => submit(suggestion)} disabled={awaiting}>
                        {suggestion}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}
      </div>
      <div className={styles.composer}>
        <span className={styles.prompt} aria-hidden="true">
          &gt;
        </span>
        <input
          ref={inputRef}
          type="text"
          className={styles.input}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          disabled={awaiting}
          aria-label={t('chat.input.label')}
          placeholder={t('chat.input.placeholder')}
        />
        <IconButton icon="send" label={t('chat.input.send')} onClick={() => submit()} disabled={!draft.trim() || awaiting} />
      </div>
    </div>
  )
}
