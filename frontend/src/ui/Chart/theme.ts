/** Light: minimised card (solid --ink, dark text). Dark: expanded view on the page background. */
export type ChartVariant = 'dark' | 'light'

/** Chart colours read from the design tokens at mount (uPlot draws on canvas: no CSS variables there). */
export interface ChartTheme {
  /** Axis labels. */
  text: string
  /** Grid lines and tick marks. */
  grid: string
  /** Fill of hollow candles (close above open). */
  surface: string
  /** Series colour: the organ group colour, or the text colour when there is none. */
  series: string
}

export function readTheme(variant: ChartVariant, seriesToken?: string): ChartTheme {
  const style = getComputedStyle(document.documentElement)
  const token = (name: string) => style.getPropertyValue(name).trim()
  if (variant === 'light') {
    return {
      text: token('--bg'),
      grid: token('--line-on-light'),
      surface: token('--ink'),
      series: token(seriesToken ?? '--bg'),
    }
  }
  return {
    text: token('--ink-3'),
    grid: token('--line'),
    surface: token('--bg'),
    series: token(seriesToken ?? '--ink'),
  }
}
