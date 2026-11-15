import { useEffect, useRef } from 'react'
import type uPlot from 'uplot'
import { readTheme, type ChartTheme, type ChartVariant } from './theme'
import type { ChartFeed } from './types'

type UPlotLib = typeof uPlot

export interface FeedPlotConfig<S> {
  feed: ChartFeed<S>
  height: number
  variant: ChartVariant
  /** Token of the series colour (organ group). */
  seriesToken?: string
  /**
   * Width of the visible x window in seconds. When set, the window slides with time between data frames,
   * so the line glides instead of jumping at each new sample. Omit for an auto-fitted x axis.
   */
  windowSeconds?: number
  format: (value: number) => string
  /** uPlot options without size. Built after uPlot is loaded, so `lib.paths` and friends are available. */
  options: (lib: UPlotLib, theme: ChartTheme, format: (value: number) => string) => Omit<uPlot.Options, 'width' | 'height'>
  toData: (snapshot: S) => uPlot.AlignedData
  /** Latest value shown in the card header, or null when there is none. */
  latest: (snapshot: S) => number | null
  onLatest: (value: number | null) => void
}

/**
 * Creates a uPlot instance on a lazily imported module and keeps it in sync with `feed`. Data arrives
 * about twice a second: the chart takes it on the next animation frame. When `windowSeconds` is set the
 * x window keeps moving between frames, from the last sample's time plus the real time elapsed since it
 * arrived. The loop stops with the page hidden and is not run for `prefers-reduced-motion`, where the
 * window only jumps when data arrives. Follows the container width; destroyed on unmount.
 */
export function useFeedPlot<S>(config: FeedPlotConfig<S>) {
  const container = useRef<HTMLDivElement>(null)
  const configRef = useRef(config)
  const feed = config.feed

  useEffect(() => {
    configRef.current = config
  })

  useEffect(() => {
    const el = container.current
    if (!el) return
    let disposed = false
    let plot: uPlot | null = null
    let frame = 0
    let dirty = false
    let lastX: number | null = null
    let lastArrival = 0
    let unsubscribe: () => void = () => {}
    let observer: ResizeObserver | null = null
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

    const slides = () => configRef.current.windowSeconds !== undefined && lastX !== null
    // The loop runs only while the window must move with time: the page is visible and motion is allowed.
    const runsContinuously = () => slides() && !reducedMotion.matches && document.visibilityState === 'visible'

    const tick = () => {
      frame = 0
      if (disposed || !plot) return
      const current = configRef.current
      if (dirty) {
        dirty = false
        const snapshot = current.feed.read()
        const data = current.toData(snapshot)
        plot.setData(data, true)
        const xs = data[0]
        lastX = xs.length > 0 ? (xs[xs.length - 1] ?? null) : null
        lastArrival = performance.now()
        current.onLatest(current.latest(snapshot))
      }
      if (slides() && current.windowSeconds !== undefined && lastX !== null) {
        const elapsed = reducedMotion.matches ? 0 : (performance.now() - lastArrival) / 1000
        const max = lastX + elapsed
        plot.setScale('x', { min: max - current.windowSeconds, max })
      }
      if (runsContinuously()) frame = requestAnimationFrame(tick)
    }

    const schedule = () => {
      dirty = true
      if (!frame) frame = requestAnimationFrame(tick)
    }
    const onVisibility = () => {
      if (!frame && runsContinuously()) frame = requestAnimationFrame(tick)
    }

    Promise.all([import('uplot'), import('uplot/dist/uPlot.min.css')]).then(([module]) => {
      if (disposed) return
      const UPlot = module.default
      const current = configRef.current
      const { options, toData, format, height } = current
      plot = new UPlot(
        {
          ...options(UPlot, readTheme(current.variant, current.seriesToken), format),
          width: el.clientWidth,
          height,
        },
        toData(current.feed.read()),
        el,
      )
      unsubscribe = current.feed.subscribe(schedule)
      observer = new ResizeObserver(() => plot?.setSize({ width: el.clientWidth, height: el.clientHeight || height }))
      observer.observe(el)
      document.addEventListener('visibilitychange', onVisibility)
      schedule()
    })

    // Teardown releases everything the chart holds: the animation frame, the page and feed listeners,
    // the resize observer and the uPlot instance (its DOM, listeners and data arrays). The reference is
    // dropped so the instance can be collected. A late import or frame sees `disposed` and does nothing.
    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      frame = 0
      document.removeEventListener('visibilitychange', onVisibility)
      unsubscribe()
      observer?.disconnect()
      observer = null
      plot?.destroy()
      plot = null
    }
  }, [feed])

  return container
}
