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

const CARD_HEIGHT = 148
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
  /**
   * The crew member's own baseline for this measure: drawn as a dashed line with `baselineLabel`, and kept
   * inside the y scale. Read when the chart mounts; give the chart a new `key` when it changes.
   */
  baseline?: number
  /** Translated text next to the baseline line (e.g. "baseline 54"). */
  baselineLabel?: string
}

/** Dash and gap of the baseline line, in CSS pixels. */
const BASELINE_DASH = 4
/** Room above and below the data and the baseline, as a share of their span. */
const Y_PAD = 0.15

/** y range that holds the data and the baseline, with some room. Missing data falls back to the baseline. */
function rangeWithBaseline(baseline: number) {
  return (_: uPlot, min: number | null, max: number | null): [number, number] => {
    const low = Math.min(min ?? baseline, baseline)
    const high = Math.max(max ?? baseline, baseline)
    const pad = (high - low) * Y_PAD || Math.max(1, Math.abs(baseline) * 0.05)
    return [low - pad, high + pad]
  }
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
  baseline,
  baselineLabel,
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
    variant: expanded ? 'expanded' : 'card',
    windowSeconds: expanded ? EXPANDED_WINDOW_SECONDS : CARD_WINDOW_SECONDS,
    seriesToken,
    format,
    options: (lib, theme, fmt) => ({
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, points: { show: false } },
      scales: {
        x: { time: true },
        y: range ? { range } : baseline !== undefined ? { range: rangeWithBaseline(baseline) } : {},
      },
      axes: chartAxes(theme, fmt, time),
      hooks:
        baseline === undefined
          ? {}
          : {
              draw: [
                (u: uPlot) => {
                  const ratio = lib.pxRatio
                  const y = u.valToPos(baseline, 'y', true)
                  const { left, width } = u.bbox
                  const ctx = u.ctx
                  ctx.save()
                  ctx.strokeStyle = theme.baseline
                  ctx.lineWidth = ratio
                  ctx.setLineDash([BASELINE_DASH * ratio, BASELINE_DASH * ratio])
                  ctx.beginPath()
                  ctx.moveTo(left, y)
                  ctx.lineTo(left + width, y)
                  ctx.stroke()
                  if (baselineLabel) {
                    ctx.fillStyle = theme.text
                    ctx.font = `${Math.round(10 * ratio)}px ${theme.font}`
                    ctx.textAlign = 'right'
                    ctx.textBaseline = 'bottom'
                    ctx.fillText(baselineLabel, left + width - 2 * ratio, y - 2 * ratio)
                  }
                  ctx.restore()
                },
              ],
            },
      series: [
        {},
        {
          stroke: theme.series,
          fill: curve === 'stepped' ? undefined : theme.fill,
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
