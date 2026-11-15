import { useState, type KeyboardEvent } from 'react'
import { useChat } from '@/lib/data/chat'
import { useI18n } from '@/lib/i18n'
import { Chip } from '@/ui/Chip'
import { Drawer } from '@/ui/Drawer'
import { IconButton } from '@/ui/IconButton'
import styles from './ChatDrawer.module.css'

/** Narrow assistant sidebar, collapsed by default. Messages are mock replies for now. */
export function ChatDrawer() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [draft, setDraft] = useState('')
  const messages = useChat((state) => state.messages)
  const send = useChat((state) => state.send)

  // DOM order is newest first: with column-reverse the newest message sits at the bottom.
  const newestFirst = [...messages].reverse()

  const submit = () => {
    if (!draft.trim()) return
    send(draft)
    setDraft('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') submit()
  }

  return (
    <Drawer
      open={open}
      onOpenChange={setOpen}
      icon="chat"
      title={t('chat.drawer.title')}
      openLabel={t('chat.drawer.open')}
      closeLabel={t('chat.drawer.close')}
      expand={{
        expanded,
        onExpandedChange: setExpanded,
        expandLabel: t('chat.drawer.expand'),
        collapseLabel: t('chat.drawer.collapse'),
      }}
    >
      <div className={styles.chat}>
        <div className={styles.messages} role="log" aria-live="polite" aria-label={t('chat.drawer.title')}>
          {messages.length === 0 && <p className={styles.empty}>{t('chat.drawer.empty')}</p>}
          {newestFirst.map((message) => (
            <div key={message.id} className={message.role === 'user' ? styles.rowUser : styles.rowAssistant}>
              <Chip solid={message.role === 'assistant'} className={styles.bubble}>
                {message.text}
              </Chip>
            </div>
          ))}
        </div>
        <div className={styles.composer}>
          <input
            type="text"
            className={styles.input}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
            aria-label={t('chat.input.label')}
            placeholder={t('chat.input.placeholder')}
          />
          <IconButton icon="send" label={t('chat.input.send')} onClick={submit} disabled={!draft.trim()} />
        </div>
      </div>
    </Drawer>
  )
}
