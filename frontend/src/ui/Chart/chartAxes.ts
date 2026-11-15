import type uPlot from 'uplot'
import type { ChartTheme } from './theme'

/** Canvas font in px (canvas does not read rem). Small on purpose: the current value carries the emphasis. */
const AXIS_FONT = '10px "Ubuntu Mono", ui-monospace, monospace'

/** Clock time only (no date). Seconds are added in the expanded view. */
export function timeFormatter(locale: string, withSeconds: boolean): (seconds: number) => string {
  const format = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    second: withSeconds ? '2-digit' : undefined,
  }).format
  return (seconds) => format(new Date(seconds * 1000))
}

export function chartAxes(
  theme: ChartTheme,
  format: (value: number) => string,
  time: (seconds: number) => string,
): uPlot.Axis[] {
  const common = {
    stroke: theme.text,
    font: AXIS_FONT,
    grid: { stroke: theme.grid, width: 1 },
    ticks: { stroke: theme.grid, width: 1 },
  }
  return [
    { ...common, values: (_self: uPlot, values: number[]) => values.map(time) },
    { ...common, size: 40, values: (_self: uPlot, values: number[]) => values.map(format) },
  ]
}

/** Last `count` items, or all of them when no limit is given. */
export function tail<T>(values: T[], count: number | undefined): T[] {
  return count === undefined || values.length <= count ? values : values.slice(values.length - count)
}

export function lastValue<T>(values: (T | null)[]): T | null {
  return values.length === 0 ? null : (values[values.length - 1] ?? null)
}
