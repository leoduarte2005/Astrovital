import { memo, useMemo, useRef } from 'react'
import type uPlot from 'uplot'
import { useI18n } from '@/lib/i18n'
import { ChartFrame } from './ChartFrame'
import { ExpandableChart } from './ExpandableChart'
import { chartAxes, lastValue, tail, timeFormatter } from './chartAxes'
import { useFeedPlot } from './useFeedPlot'
import type { ChartTheme } from './theme'
import { CARD_READINGS, EXPANDED_READINGS, type ChartFeed, type OhlcSnapshot } from './types'
import plotStyles from './Plot.module.css'

const CARD_HEIGHT = 112
const EXPANDED_HEIGHT = 360

export interface OhlcChartProps {
  title: string
  feed: ChartFeed<OhlcSnapshot>
  unit: string
  decimals: number
  /** Width of one bucket in seconds: sets the candle width on screen. */
  bucketSeconds: number
  range?: [number, number]
  message: string | null
  /** Token of the organ group colour for the candles. Default: the text colour. */
  seriesToken?: string
}

interface CardProps extends OhlcChartProps {
  expanded: boolean
  onExpand?: () => void
}

/** Draws one candle per bucket: wick from low to high, body from open to close. Hollow = close above open. */
function drawCandles(u: uPlot, theme: ChartTheme, bucketSeconds: number) {
  const [xs, opens, highs, lows, closes] = u.data as unknown as [
    number[],
    (number | null)[],
    (number | null)[],
    (number | null)[],
    (number | null)[],
  ]
  if (!xs || xs.length === 0) return
  const span = Math.max(1, (u.scales.x?.max ?? 0) - (u.scales.x?.min ?? 0))
  const pxPerSecond = u.bbox.width / span
  const half = Math.min(9, Math.max(2, pxPerSecond * bucketSeconds * 0.3))
  const ctx = u.ctx
  ctx.save()
  ctx.lineWidth = Math.max(1, window.devicePixelRatio)
  ctx.strokeStyle = theme.series
  for (let i = 0; i < xs.length; i++) {
    const open = opens[i]
    const high = highs[i]
    const low = lows[i]
    const close = closes[i]
    if (open == null || high == null || low == null || close == null) continue
    const x = u.valToPos(xs[i] ?? 0, 'x', true)
    const yHigh = u.valToPos(high, 'y', true)
    const yLow = u.valToPos(low, 'y', true)
    const yOpen = u.valToPos(open, 'y', true)
    const yClose = u.valToPos(close, 'y', true)
    ctx.beginPath()
    ctx.moveTo(x, yHigh)
    ctx.lineTo(x, yLow)
    ctx.stroke()
    const top = Math.min(yOpen, yClose)
    const height = Math.max(1, Math.abs(yClose - yOpen))
    ctx.fillStyle = close >= open ? theme.surface : theme.series
    ctx.fillRect(x - half, top, half * 2, height)
    ctx.strokeRect(x - half, top, half * 2, height)
  }
  ctx.restore()
}

function CandleCard({
  title,
  feed,
  unit,
  decimals,
  bucketSeconds,
  range,
  message,
  seriesToken,
  expanded,
  onExpand,
}: CardProps) {
  const { locale } = useI18n()
  const valueRef = useRef<HTMLSpanElement>(null)
  const format = useMemo(
    () => new Intl.NumberFormat(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format,
    [locale, decimals],
  )
  const time = useMemo(() => timeFormatter(locale, expanded), [locale, expanded])
  const readings = expanded ? EXPANDED_READINGS : CARD_READINGS

  const container = useFeedPlot<OhlcSnapshot>({
    feed,
    height: expanded ? EXPANDED_HEIGHT : CARD_HEIGHT,
    variant: expanded ? 'dark' : 'light',
    seriesToken,
    format,
    options: (_lib, theme, fmt) => {
      // Series only feed the y scale and the cursor: the candles are drawn in the draw hook.
      const hidden = { stroke: 'transparent', points: { show: false }, paths: () => null }
      return {
        legend: { show: false },
        cursor: { drag: { x: false, y: false }, points: { show: false } },
        scales: { x: { time: true }, y: range ? { range } : {} },
        axes: chartAxes(theme, fmt, time),
        series: [{}, hidden, hidden, hidden, hidden],
        hooks: { draw: [(u: uPlot) => drawCandles(u, theme, bucketSeconds)] },
      }
    },
    toData: (snapshot) =>
      [
        tail(snapshot.x, readings),
        tail(snapshot.open, readings),
        tail(snapshot.high, readings),
        tail(snapshot.low, readings),
        tail(snapshot.close, readings),
      ] as unknown as uPlot.AlignedData,
    latest: (snapshot) => lastValue(snapshot.close),
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

/** Open / high / low / close per time bucket, for one vital. Buckets with no value are left empty. */
export const OhlcChart = memo(function OhlcChart(props: OhlcChartProps) {
  return (
    <ExpandableChart
      title={props.title}
      renderChart={(expanded, onExpand) => <CandleCard {...props} expanded={expanded} onExpand={onExpand} />}
    />
  )
})
