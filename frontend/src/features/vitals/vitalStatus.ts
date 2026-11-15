import { useEffect, useState } from 'react'
import { useConnection } from '@/lib/data'
import type { MessageKey } from '@/lib/i18n'
import { vitalFeed } from './vitalFeed'

/** Older than this, the last frame is reported as "last data …" instead of live. */
const STALE_MS = 5000

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

function ago(ms: number, locale: string): string {
  const format = new Intl.RelativeTimeFormat(locale, { numeric: 'always' })
  const seconds = Math.max(1, Math.round(ms / 1000))
  return seconds < 60 ? format.format(-seconds, 'second') : format.format(-Math.round(seconds / 60), 'minute')
}

/** Text shown in place of the plots when there is nothing to plot. Null while data is flowing. */
function statusMessage(
  connection: 'connecting' | 'live' | 'offline',
  frameAt: number | null,
  now: number,
  t: (key: MessageKey, params?: Record<string, string | number>) => string,
  locale: string,
): string | null {
  if (connection === 'connecting') return t('chart.connecting')
  if (frameAt === null) return connection === 'live' ? t('chart.waiting') : t('chart.offline')
  const age = now - frameAt
  if (connection === 'offline') return `${t('chart.offline')} · ${t('chart.stale', { ago: ago(age, locale) })}`
  if (age > STALE_MS) return t('chart.stale', { ago: ago(age, locale) })
  return null
}

/** The status text for a group of charts. Re-evaluated once a second and on connection changes. */
export function useStatusMessage(t: (key: MessageKey, params?: Record<string, string | number>) => string, locale: string) {
  const connection = useConnection((state) => state.state)
  const now = useNow(1000)
  return statusMessage(connection, vitalFeed.lastFrame(), now, t, locale)
}
