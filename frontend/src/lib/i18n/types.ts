import type en from './locales/en.json'

export const LOCALES = ['en', 'es', 'zh', 'pt'] as const
export type Locale = (typeof LOCALES)[number]

/** Message keys are derived from the English file (source of truth). */
export type MessageKey = keyof typeof en
export type Messages = Record<MessageKey, string>

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value)
}
