import { memo, useMemo, useRef } from 'react'
import type uPlot from 'uplot'
import { useI18n } from '@/lib/i18n'
import { ChartFrame } from './ChartFrame'
import { ExpandableChart } from './ExpandableChart'
import { chartAxes, lastValue, tail, timeFormatter } from './chartAxes'
import { useFeedPlot } from './useFeedPlot'
import {
  CARD_READINGS,
  CARD_WINDOW_SECONDS,
  EXPANDED_READINGS,
  EXPANDED_WINDOW_SECONDS,
  type ChartFeed,
  type LineSnapshot,
} from './types'
import plotStyles from './Plot.module.css'

const CARD_HEIGHT = 96
const EXPANDED_HEIGHT = 360

export interface SmoothLineChartProps {
  title: string
  feed: ChartFeed<LineSnapshot>
  /** Symbol shown next to the value. Not translated (rules/i18n.md). */
  unit: string
  decimals: number
  /** Fixed y scale for values with a known range. Omit to auto-fit. */
  range?: [number, number]
  /** Informative text instead of the plot (no data, connecting, offline). */
  message: string | null
  /** Token of the organ group colour for the series. Default: the text colour. */
  seriesToken?: string
  /** Formats axis ticks and the header value (e.g. severity labels). Default: locale number. */
  valueFormat?: (value: number) => string
  /** Path shape: `smooth` (spline, default), `linear` (straight segments) or `stepped` (categorical values, e.g. severity). */
  curve?: 'smooth' | 'linear' | 'stepped'
}

interface CardProps extends SmoothLineChartProps {
  expanded: boolean
  onExpand?: () => void
}

function LineCard({
  title,
  feed,
  unit,
  decimals,
  range,
  message,
  seriesToken,
  valueFormat,
  curve = 'smooth',
  expanded,
  onExpand,
}: CardProps) {
  const { locale } = useI18n()
  const valueRef = useRef<HTMLSpanElement>(null)
  const numberFormat = useMemo(
    () => new Intl.NumberFormat(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format,
    [locale, decimals],
  )
  const format = valueFormat ?? numberFormat
  const time = useMemo(() => timeFormatter(locale, expanded), [locale, expanded])
  const readings = expanded ? EXPANDED_READINGS : CARD_READINGS

  const container = useFeedPlot<LineSnapshot>({
    feed,
    height: expanded ? EXPANDED_HEIGHT : CARD_HEIGHT,
    variant: expanded ? 'dark' : 'light',
    windowSeconds: expanded ? EXPANDED_WINDOW_SECONDS : CARD_WINDOW_SECONDS,
    seriesToken,
    format,
    options: (lib, theme, fmt) => ({
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, points: { show: false } },
      scales: { x: { time: true }, y: range ? { range } : {} },
      axes: chartAxes(theme, fmt, time),
      series: [
        {},
        {
          stroke: theme.series,
          width: 1.5,
          spanGaps: false,
          points: { show: false },
          paths:
            curve === 'stepped'
              ? lib.paths.stepped?.({ align: 1 })
              : curve === 'linear'
                ? lib.paths.linear?.()
                : lib.paths.spline?.(),
        },
      ],
    }),
    toData: (snapshot) => [tail(snapshot.x, readings), tail(snapshot.y, readings)] as unknown as uPlot.AlignedData,
    latest: (snapshot) => lastValue(snapshot.y),
    onLatest: (value) => {
      if (valueRef.current) valueRef.current.textContent = value === null ? '—' : format(value)
    },
  })

  return (
    <ChartFrame title={title} unit={unit} valueRef={valueRef} message={message} onExpand={onExpand} expanded={expanded}>
      <div ref={container} className={plotStyles.plot} hidden={message !== null} />
    </ChartFrame>
  )
}

/** Line over time, for one vital. Gaps (`null`) are left empty, never drawn as zero. */
export const SmoothLineChart = memo(function SmoothLineChart(props: SmoothLineChartProps) {
  return (
    <ExpandableChart
      title={props.title}
      renderChart={(expanded, onExpand) => <LineCard {...props} expanded={expanded} onExpand={onExpand} />}
    />
  )
})
