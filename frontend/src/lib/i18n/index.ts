import { useSyncExternalStore } from 'react'
import en from './locales/en.json'
import type { Locale, MessageKey, Messages } from './types'

export { LOCALES, isLocale } from './types'
export type { Locale, MessageKey } from './types'

// Only the active locale is loaded; English is bundled as the fallback.
const loaders: Record<Locale, () => Promise<{ default: Messages }>> = {
  en: () => Promise.resolve({ default: en }),
  es: () => import('./locales/es.json'),
  pt: () => import('./locales/pt.json'),
  zh: () => import('./locales/zh.json'),
}

let state = { locale: 'en' as Locale, messages: en as Messages }
const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export async function setLocale(locale: Locale): Promise<void> {
  const { default: messages } = await loaders[locale]()
  state = { locale, messages }
  document.documentElement.lang = locale
  listeners.forEach((listener) => listener())
}

export function t(key: MessageKey, params?: Record<string, string | number>): string {
  const template = state.messages[key] ?? (en as Messages)[key]
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`))
}

/** Subscribes a component to locale changes; returns `t` bound to the active locale. */
export function useI18n() {
  const current = useSyncExternalStore(subscribe, () => state)
  return { locale: current.locale, t }
}

/** Joins items with the active locale's list rules ("a, b and c"). */
export function formatList(items: string[]): string {
  return new Intl.ListFormat(state.locale, { style: 'long', type: 'conjunction' }).format(items)
}
