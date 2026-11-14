import { isLocale, type Locale } from '@/lib/i18n'

export interface RuntimeConfig {
  source: 'mock' | 'live'
  locale: Locale
}

const DEFAULTS: RuntimeConfig = { source: 'mock', locale: 'en' }

/** Reads /config.json (relative path, served next to the app) so settings change without a rebuild. */
export async function loadConfig(): Promise<RuntimeConfig> {
  try {
    const response = await fetch('./config.json', { cache: 'no-store' })
    if (!response.ok) return DEFAULTS
    const raw: Partial<Record<keyof RuntimeConfig, unknown>> = await response.json()
    return {
      source: raw.source === 'live' ? 'live' : 'mock',
      locale: isLocale(raw.locale) ? raw.locale : DEFAULTS.locale,
    }
  } catch (error) {
    console.warn('config.json unavailable, using defaults', error)
    return DEFAULTS
  }
}
