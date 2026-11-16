import { memo, useMemo } from 'react'
import type uPlot from 'uplot'
import type { Corridor, CorridorState } from '@/lib/model/baseline'
import { useI18n } from '@/lib/i18n'
import { Icon } from '@/ui/Icon'
import { IconButton } from '@/ui/IconButton'
import { chartAxes } from './chartAxes'
import { useStaticPlot } from './useStaticPlot'
import plotStyles from './Plot.module.css'
import styles from './CorridorChart.module.css'

const PLOT_HEIGHT = 168
const PLOT_HEIGHT_EXPANDED = 360

export interface CorridorChartProps {
  title: string
  /** What the series says in words, e.g. "HRV is 12% below your corridor." Already translated. */
  summary: string
  state: CorridorState
  /** Translated label of the state. Shown with an icon when outside: never colour alone. */
  stateLabel: string
  x: number[]
  y: number[]
  corridor: Corridor
  xFormat: (seconds: number) => string
  format: (value: number) => string
  /** Shown instead of the plot when there is no data. */
  emptyMessage: string
  /** Opens the chart in the large view. Omit inside that view. */
  onExpand?: () => void
  /** Inside the modal: dark surface, taller plot, no title (the dialog shows it). */
  expanded?: boolean
}

/**
 * A measure against the crew member's own corridor: the corridor is shaded, the real line is on top. Solid
 * dark panel card, like the other minimised charts. The text summary is the main reading; the plot is the detail.
 */
export const CorridorChart = memo(function CorridorChart({
  title,
  summary,
  state,
  stateLabel,
  x,
  y,
  corridor,
  xFormat,
  format,
  emptyMessage,
  onExpand,
  expanded = false,
}: CorridorChartProps) {
  const { t } = useI18n()
  const data = useMemo(
    () => [x, y, x.map(() => corridor.high), x.map(() => corridor.low)] as unknown as uPlot.AlignedData,
    [x, y, corridor],
  )

  const container = useStaticPlot({
    height: expanded ? PLOT_HEIGHT_EXPANDED : PLOT_HEIGHT,
    variant: expanded ? 'expanded' : 'card',
    data,
    options: (_lib, theme) => {
      // The two edge series only draw the shaded band between them; the line is the real data.
      const edge = { stroke: 'transparent', points: { show: false } }
      return {
        legend: { show: false },
        cursor: { drag: { x: false, y: false }, points: { show: false } },
        scales: { x: { time: true } },
        axes: chartAxes(theme, format, xFormat),
        series: [{}, { stroke: theme.series, width: 1.5, points: { show: false } }, edge, edge],
        bands: [{ series: [2, 3] as [number, number], fill: theme.grid }],
      }
    },
  })

  const empty = x.length === 0
  return (
    <section className={expanded ? `${styles.root} ${styles.expanded}` : styles.root} aria-label={title}>
      <header className={styles.header}>
        {!expanded && <h3 className={styles.title}>{title}</h3>}
        <span className={styles.state} data-state={state}>
          {state !== 'inside' && <Icon name="alert" />}
          {stateLabel}
        </span>
        {onExpand && <IconButton icon="expand" label={t('chart.expand')} onClick={onExpand} size="sm" iconSize="sm" />}
      </header>
      <p className={styles.summary}>{summary}</p>
      {empty && <p className={styles.empty}>{emptyMessage}</p>}
      <div ref={container} className={plotStyles.plot} hidden={empty} />
    </section>
  )
})
