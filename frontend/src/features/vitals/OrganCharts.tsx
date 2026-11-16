import { t, useI18n, type MessageKey } from '@/lib/i18n'
import { SmoothLineChart, StatusChart } from '@/ui/Chart'
import { ORGAN_GROUPS } from './organGroups'
import { SEVERITY } from './vitalSpecs'
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

const SUBSYSTEM_SPECS = Object.values(SEVERITY)

/** The six subsystems as the central classifies them, one compact status each. Shown when no organ is selected. */
export function SubsystemCharts() {
  const { t: translate, locale } = useI18n()
  const message = useStatusMessage(translate, locale)
  return (
    <div className={styles.stack}>
      {SUBSYSTEM_SPECS.map((spec) => (
        <StatusChart
          key={spec.id}
          title={translate(spec.labelKey)}
          feed={vitalFeed.lineFeed(spec.id)}
          message={message}
          valueFormat={severityLabel}
          kind="severity"
        />
      ))}
    </div>
  )
}

interface OrganChartsProps {
  organ: string
  /** The crew member's own baseline by vital id (e.g. `heartRate`), from the crew context. */
  baselines?: Partial<Record<string, number>>
}

/**
 * The chart group of the selected marker. Charts exist only while their marker is selected, and each reads
 * only the confirmed crew member's data from the shared feed. A vital with a baseline draws it as a dashed line.
 */
export function OrganCharts({ organ, baselines }: OrganChartsProps) {
  const { t: translate, locale } = useI18n()
  const message = useStatusMessage(translate, locale)
  const group = ORGAN_GROUPS[organ]
  if (!group) return null

  const baselineLabel = (value: number, decimals: number) =>
    translate('chart.baseline', {
      value: new Intl.NumberFormat(locale, { maximumFractionDigits: decimals }).format(value),
    })

  return (
    <div className={styles.stack}>
      {group.charts.map(({ spec, curve, labels }) => (
        labels ? (
          <StatusChart
            key={spec.id}
            title={translate(spec.labelKey)}
            feed={vitalFeed.lineFeed(spec.id)}
            message={message}
            valueFormat={labels === 'severity' ? severityLabel : categoryLabel(spec.id)}
            kind={labels}
          />
        ) : (
          // The baseline is read at mount: the key remounts the chart when the crew context arrives.
          <SmoothLineChart
            key={`${spec.id}:${baselines?.[spec.id] ?? '-'}`}
            title={translate(spec.labelKey)}
            feed={vitalFeed.lineFeed(spec.id)}
            unit={spec.unit}
            decimals={spec.decimals}
            range={spec.range}
            message={message}
            seriesToken={group.seriesToken}
            curve={curve}
            baseline={baselines?.[spec.id]}
            baselineLabel={
              baselines?.[spec.id] === undefined ? undefined : baselineLabel(baselines[spec.id] ?? 0, spec.decimals)
            }
          />
        )
      ))}
    </div>
  )
}
