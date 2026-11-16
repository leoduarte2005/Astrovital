import { useEffect, useRef } from 'react'
import type uPlot from 'uplot'
import { readTheme, type ChartTheme, type ChartVariant } from './theme'

type UPlotLib = typeof uPlot

export interface StaticPlotConfig {
  height: number
  variant: ChartVariant
  /** Token of the series colour. */
  seriesToken?: string
  /** uPlot options without size. Built after uPlot is loaded, so `lib.paths` and friends are available. */
  options: (lib: UPlotLib, theme: ChartTheme) => Omit<uPlot.Options, 'width' | 'height'>
  data: uPlot.AlignedData
}

/**
 * A uPlot instance for data that does not stream (history): created once on a lazily imported module, updated
 * when `data` changes, following the container width. Everything it holds is released on unmount: the
 * observer, the uPlot instance (DOM, listeners, data) and the reference to it. Returns the container ref.
 */
export function useStaticPlot(config: StaticPlotConfig) {
  const container = useRef<HTMLDivElement>(null)
  const plotRef = useRef<uPlot | null>(null)
  const configRef = useRef(config)

  useEffect(() => {
    configRef.current = config
  })

  useEffect(() => {
    const el = container.current
    if (!el) return
    let disposed = false
    let observer: ResizeObserver | null = null

    Promise.all([import('uplot'), import('uplot/dist/uPlot.min.css')]).then(([module]) => {
      if (disposed) return
      const UPlot = module.default
      const current = configRef.current
      const plot = new UPlot(
        { ...current.options(UPlot, readTheme(current.seriesToken)), width: el.clientWidth, height: current.height },
        current.data,
        el,
      )
      plotRef.current = plot
      observer = new ResizeObserver(() => plot.setSize({ width: el.clientWidth, height: configRef.current.height }))
      observer.observe(el)
    })

    return () => {
      disposed = true
      observer?.disconnect()
      plotRef.current?.destroy()
      plotRef.current = null
    }
  }, [])

  useEffect(() => {
    plotRef.current?.setData(config.data)
  }, [config.data])

  return container
}
