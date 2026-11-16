import { useState } from 'react'
import { useI18n } from '@/lib/i18n'
import { Drawer } from '@/ui/Drawer'
import { ChatLog } from './ChatLog'

/**
 * Narrow assistant sidebar, collapsed by default, on the pages that do not show the assistant inline. The
 * content is the same clinical log as on the medical page.
 */
export function ChatDrawer() {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)

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
      <ChatLog />
    </Drawer>
  )
}
