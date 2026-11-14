import { useI18n } from '@/lib/i18n'
import { Chip } from '@/ui/Chip'

/** Always-visible statement of what is sensing the cabin (mock: static). */
export function PrivacyIndicator() {
  const { t } = useI18n()
  return <Chip icon="signal">{t('home.privacy')}</Chip>
}
