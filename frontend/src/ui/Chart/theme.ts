/** Card: minimised chart on a panel. Expanded: the larger view in the modal. Both sit on --surface. */
export type ChartVariant = 'card' | 'expanded'

/** Chart colours read from the design tokens at mount (uPlot draws on canvas: no CSS variables there). */
export interface ChartTheme {
  /** Axis labels. */
  text: string
  /** Grid lines and tick marks. */
  grid: string
  /** Fill of hollow candles (close above open): the surface behind the plot. */
  surface: string
  /** Series colour: the organ group colour, or the text colour when there is none. */
  series: string
  /** Fill under a line series. */
  fill: string
  /** The crew member's own baseline: a quiet dashed line. */
  baseline: string
  /** Font family for labels drawn on the canvas. */
  font: string
}

export function readTheme(seriesToken?: string): ChartTheme {
  const style = getComputedStyle(document.documentElement)
  const token = (name: string) => style.getPropertyValue(name).trim()
  return {
    text: token('--ink-3'),
    grid: token('--line'),
    surface: token('--surface'),
    series: token(seriesToken ?? '--ink'),
    fill: token('--accent-tint'),
    baseline: token('--line-strong'),
    font: token('--font-mono'),
  }
}
