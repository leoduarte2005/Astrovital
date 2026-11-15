/** The 24 months of training before the mission: M01 = 2024-10 … M24 = 2026-09 (crewLore/types.ts). */
export const TRAINING_MONTHS = 24
export const MINUTES_PER_DAY = 1440
/** One simulated day lasts this long in real time: accelerated time, as in life-simulation games. */
export const SIM_DAY_MS = 240_000
/** Only every 10th day of the month is simulated (days 1, 11, 21 and 31): the simulator skips the others. */
export const DAY_STEP = 10

const FIRST_YEAR = 2024
const FIRST_MONTH = 10 // October

function yearMonth(monthIndex: number): { year: number; month: number } {
  const zeroBased = FIRST_MONTH - 1 + monthIndex
  return { year: FIRST_YEAR + Math.floor(zeroBased / 12), month: (zeroBased % 12) + 1 }
}

/** `YYYY-MM` of a training month; matches `MonthEntry.period` of the lore. */
export function periodOf(monthIndex: number): string {
  const { year, month } = yearMonth(monthIndex)
  return `${year}-${String(month).padStart(2, '0')}`
}

/** Real number of days of the month (28 to 31). */
export function daysInMonth(monthIndex: number): number {
  const { year, month } = yearMonth(monthIndex)
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

/** ISO date and weekday (0 Sunday .. 6 Saturday) of a day of a training month. */
export function dateOf(monthIndex: number, dayIndex: number): { date: string; weekday: number } {
  const { year, month } = yearMonth(monthIndex)
  const day = new Date(Date.UTC(year, month - 1, dayIndex + 1))
  return { date: day.toISOString().slice(0, 10), weekday: day.getUTCDay() }
}

/** Simulated days of a month: every `DAY_STEP`-th day, starting on the first. */
export function shownDays(monthIndex: number): number {
  return Math.ceil(daysInMonth(monthIndex) / DAY_STEP)
}

/**
 * Where the looping month is after `elapsedMs` of real time: the simulated day (one of the shown days, `DAY_STEP` apart)
 * and the minute of that day. The month repeats after its last shown day.
 */
export function simTimeAt(monthIndex: number, elapsedMs: number): { dayIndex: number; minute: number } {
  const loop = shownDays(monthIndex) * SIM_DAY_MS
  const t = ((elapsedMs % loop) + loop) % loop
  const slot = Math.floor(t / SIM_DAY_MS)
  return { dayIndex: slot * DAY_STEP, minute: ((t % SIM_DAY_MS) / SIM_DAY_MS) * MINUTES_PER_DAY }
}

/** Minutes of a clock time, e.g. `hm(7, 30)` = 450. */
export const hm = (hours: number, minutes = 0): number => hours * 60 + minutes
