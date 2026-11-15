import { t, useI18n, type MessageKey } from '@/lib/i18n'
import { SmoothLineChart } from '@/ui/Chart'
import { ORGAN_GROUPS } from './organGroups'
import { vitalFeed } from './vitalFeed'
import { useStatusMessage } from './vitalStatus'
import styles from './OrganCharts.module.css'

const SEVERITY_KEYS: MessageKey[] = ['enum.severity.GREEN', 'enum.severity.YELLOW', 'enum.severity.RED']

/*
 * Label formatters live at module level so their identity never changes: the memoised charts then skip
 * the once-a-second re-render of the group. Only whole numbers are levels or categories; the axis also
 * asks for the ticks in between, which stay blank.
 */
const severityLabel = (level: number): string => (Number.isInteger(level) ? t(SEVERITY_KEYS[level] ?? SEVERITY_KEYS[0]!) : '')

const categoryFormats = new Map<string, (index: number) => string>()
function categoryLabel(id: string): (index: number) => string {
  let format = categoryFormats.get(id)
  if (!format) {
    // Posture texts come from the central and are not translated (rules/i18n.md).
    format = (index) => (Number.isInteger(index) ? (vitalFeed.categoriesFor(id)[index] ?? '') : '')
    categoryFormats.set(id, format)
  }
  return format
}

export function hasOrganCharts(organ: string): boolean {
  return organ in ORGAN_GROUPS
}

/**
 * The chart group of the selected marker. Charts exist only while their marker is selected, and each reads
 * only the confirmed crew member's data from the shared feed.
 */
export function OrganCharts({ organ }: { organ: string }) {
  const { t: translate, locale } = useI18n()
  const message = useStatusMessage(translate, locale)
  const group = ORGAN_GROUPS[organ]
  if (!group) return null

  return (
    <div className={styles.stack}>
      {group.charts.map(({ spec, curve, labels }) => (
        <SmoothLineChart
          key={spec.id}
          title={translate(spec.labelKey)}
          feed={vitalFeed.lineFeed(spec.id)}
          unit={spec.unit}
          decimals={spec.decimals}
          range={spec.range}
          message={message}
          seriesToken={group.seriesToken}
          curve={curve}
          valueFormat={labels === 'severity' ? severityLabel : labels === 'category' ? categoryLabel(spec.id) : undefined}
        />
      ))}
    </div>
  )
}
