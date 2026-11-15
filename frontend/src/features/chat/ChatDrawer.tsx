import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { getDataSource } from '@/lib/data'
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
  // Chat messages need the live link even outside the home: the drawer holds its own reference on it.
  useEffect(() => {
    const source = getDataSource()
    source.open()
    return () => source.close()
  }, [])
  const [expanded, setExpanded] = useState(false)
  const [draft, setDraft] = useState('')
  const messages = useChat((state) => state.messages)
  const send = useChat((state) => state.send)
  const awaiting = useChat((state) => state.pendingId !== null)
  const lastRole = useChat((state) => state.messages.at(-1)?.role ?? null)
  const inputRef = useRef<HTMLInputElement>(null)
  const previous = useRef({ awaiting, lastRole })

  // Focus the input when the assistant has answered and the input is enabled again. The reply lands
  // before the pending flag clears, so the focus waits for the second change. Only changes focus: mounting
  // the drawer with an old reply does not steal it.
  useEffect(() => {
    const answered =
      (previous.current.awaiting && !awaiting) || (lastRole === 'assistant' && previous.current.lastRole !== 'assistant')
    previous.current = { awaiting, lastRole }
    if (answered && !awaiting) inputRef.current?.focus()
  }, [awaiting, lastRole])

  // DOM order is newest first: with column-reverse the newest message sits at the bottom.
  const newestFirst = [...messages].reverse()

  const submit = () => {
    console.log('[chat:diag] submit', { draftLength: draft.trim().length, awaiting })
    if (!draft.trim() || awaiting) return
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
          <IconButton icon="send" label={t('chat.input.send')} onClick={submit} disabled={!draft.trim() || awaiting} />
        </div>
      </div>
    </Drawer>
  )
}
