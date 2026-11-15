import { LiveSource } from './live/LiveSource'
import { MockSource } from './mock/MockSource'
import type { DataSource } from './source'

export type { DataSource } from './source'
export { useConnection } from './connection'

let current: DataSource | null = null

/** Connects to the same origin (`/ws`), so no host is hardcoded. */
function liveUrl(): string {
  const url = new URL('ws', window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.href
}

/**
 * Creates the source. Does not connect: the live link opens when the home mounts (`open()`).
 * Idempotent: a second call closes the previous source first (React StrictMode runs effects twice in dev).
 */
export function initDataSource(kind: 'mock' | 'live'): void {
  current?.close()
  current = kind === 'live' ? new LiveSource(liveUrl()) : new MockSource()
}

export function getDataSource(): DataSource {
  if (!current) throw new Error('DataSource not initialised')
  return current
}
